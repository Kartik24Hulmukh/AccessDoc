"""Phase 6 — Hostile ZIP validation adversarial tests.

Every test constructs a deliberately hostile or malformed ZIP and asserts
that validate_bundle() rejects it with a non-empty errors list.  A valid
bundle is also built end-to-end as a positive control.
"""
import base64
import hashlib
import io
import json
import unittest
import zipfile

from app.bundle import (
    ALLOWED_MEMBER_NAMES,
    MAX_COMPRESSED_INPUT_BYTES,
    MAX_MEMBER_COUNT,
    MAX_MEMBER_EXPANDED_BYTES,
    MAX_TOTAL_EXPANDED_BYTES,
    MAX_COMPRESSION_RATIO,
    SCHEMA_VERSION,
    build_bundle,
    validate_bundle,
)
from app.service import build_artifacts

SAMPLE_BODY = {
    "scanner_input": json.dumps({
        "url": "https://example.com",
        "testEngine": {"name": "axe-core", "version": "4.11.2"},
        "violations": [
            {"id": "image-alt", "impact": "critical",
             "description": "Images must have alternate text",
             "helpUrl": "https://dequeuniversity.com/rules/axe/4.11/image-alt",
             "nodes": [{"html": "<img>"}]}
        ],
        "passes": [], "incomplete": []
    }),
    "client_name": "Test Client",
    "agency_name": "Test Agency",
    "audit_date": "2026-07-23",
}


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _valid_bundle_bytes():
    """Build a genuine valid bundle via the real pipeline."""
    arts = build_artifacts(SAMPLE_BODY)
    return build_bundle(arts)


def _read_valid_members():
    """Return {name: bytes} for every member of a valid bundle."""
    data = _valid_bundle_bytes()
    members = {}
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            members[name] = zf.read(name)
    return members


def _build_zip(members, *, compress=zipfile.ZIP_DEFLATED):
    """Build a raw ZIP from an ordered {name: bytes} mapping.

    Unlike build_bundle, this does NOT add a manifest or attestation
    automatically — the caller controls every byte, which is necessary
    for adversarial tests.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compress) as zf:
        for name, data in members.items():
            info = zipfile.ZipInfo()
            info.filename = name
            info.compress_type = compress
            info.external_attr = 0o644 << 16
            zf.writestr(info, data)
    return buf.getvalue()


def _make_manifest(files):
    """Build a manifest.json bytes object from a list of (path, sha256)."""
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "files": [{"path": p, "sha256": s} for p, s in files],
    }
    return json.dumps(manifest, indent=2).encode()


def _valid_manifest_for(members):
    """Build a correct manifest for the given {name: bytes} (excluding manifest.json)."""
    files = [(name, _sha256(data)) for name, data in members.items()
             if name != "manifest.json"]
    return _make_manifest(files)


def _valid_attestation_for(members):
    """Build a correct in-toto attestation for the given members (excluding itself)."""
    from app.intoto import build_intoto_bundle
    attested = {n: d for n, d in members.items()
                if n != "attestation.intoto.json" and n != "manifest.json"}
    return build_intoto_bundle(attested, timestamp="2026-07-23T00:00:00Z")


def _build_valid_bundle_with_extra(members):
    """Assemble a complete bundle from members dict, adding correct manifest + attestation."""
    # Remove manifest/attestation if present so we can rebuild them
    core = {n: d for n, d in members.items()
            if n not in ("manifest.json", "attestation.intoto.json")}
    core["attestation.intoto.json"] = _valid_attestation_for(core)
    core["manifest.json"] = _valid_manifest_for(core)
    return _build_zip(core)


class ZipHardeningTests(unittest.TestCase):
    # ------------------------------------------------------------------
    # Positive control
    # ------------------------------------------------------------------
    def test_valid_bundle_passes(self):
        """A real bundle built by build_bundle must still validate."""
        result = validate_bundle(_valid_bundle_bytes())
        self.assertTrue(result["valid"], msg=result["errors"])

    # ------------------------------------------------------------------
    # 6.4 — duplicate member names
    # ------------------------------------------------------------------
    def test_duplicate_report_pdf(self):
        """Duplicate report.pdf entry must be rejected."""
        members = _read_valid_members()
        # Build a ZIP with report.pdf appearing twice.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in members.items():
                info = zipfile.ZipInfo(filename=name)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                zf.writestr(info, data)
            # Add a second report.pdf
            info2 = zipfile.ZipInfo(filename="report.pdf")
            info2.compress_type = zipfile.ZIP_DEFLATED
            info2.external_attr = 0o644 << 16
            zf.writestr(info2, b"fake duplicate")
        result = validate_bundle(buf.getvalue())
        self.assertFalse(result["valid"])
        self.assertTrue(any("duplicate" in e for e in result["errors"]))

    def test_duplicate_manifest_json(self):
        """Duplicate manifest.json must be rejected."""
        members = _read_valid_members()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in members.items():
                info = zipfile.ZipInfo(filename=name)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                zf.writestr(info, data)
            info2 = zipfile.ZipInfo(filename="manifest.json")
            info2.compress_type = zipfile.ZIP_DEFLATED
            info2.external_attr = 0o644 << 16
            zf.writestr(info2, members["manifest.json"])
        result = validate_bundle(buf.getvalue())
        self.assertFalse(result["valid"])
        self.assertTrue(
            any("manifest.json" in e and "1" not in e.split(":")[0]
                for e in result["errors"])
        )

    def test_duplicate_manifest_paths(self):
        """Manifest listing the same path twice must be rejected."""
        members = _read_valid_members()
        # Build a manifest with a duplicate path entry.
        files = []
        for name, data in members.items():
            if name == "manifest.json":
                continue
            files.append((name, _sha256(data)))
        # Duplicate the first entry.
        files.append((files[0][0], files[0][1]))
        members["manifest.json"] = _make_manifest(files)
        data = _build_zip(members)
        result = validate_bundle(data)
        self.assertFalse(result["valid"])
        self.assertTrue(any("duplicate manifest path" in e for e in result["errors"]))

    # ------------------------------------------------------------------
    # 6.4 — ZIP bomb / compression ratio
    # ------------------------------------------------------------------
    def test_zip_bomb(self):
        """A small compressed input that expands enormously must be rejected."""
        # Create a highly compressible payload: repeated zeros.
        # Compressed size will be tiny, expanded size huge → ratio > 100:1.
        bomb_payload = b"\x00" * (MAX_COMPRESSION_RATIO * 1024 + 1)
        members = _read_valid_members()
        members["report.pdf"] = bomb_payload
        # Rebuild manifest + attestation to match so the only failure is the bomb.
        core = {n: d for n, d in members.items()
                if n not in ("manifest.json", "attestation.intoto.json")}
        core["attestation.intoto.json"] = _valid_attestation_for(core)
        core["manifest.json"] = _valid_manifest_for(core)
        data = _build_zip(core)
        result = validate_bundle(data)
        self.assertFalse(result["valid"])
        # Should be caught by compression ratio or expanded size limit.
        self.assertTrue(
            any("compression ratio" in e or "expanded size" in e
                or "total expanded" in e for e in result["errors"]),
            msg=result["errors"],
        )

    def test_high_compression_ratio(self):
        """A member with ratio > 100:1 must be rejected even if total size is OK."""
        # 200:1 ratio — 200 KiB expanded, ~1 KiB compressed.
        payload = b"A" * (200 * 1024)
        members = _read_valid_members()
        members["report.pdf"] = payload
        core = {n: d for n, d in members.items()
                if n not in ("manifest.json", "attestation.intoto.json")}
        core["attestation.intoto.json"] = _valid_attestation_for(core)
        core["manifest.json"] = _valid_manifest_for(core)
        data = _build_zip(core)
        result = validate_bundle(data)
        self.assertFalse(result["valid"])
        self.assertTrue(any("compression ratio" in e for e in result["errors"]))

    # ------------------------------------------------------------------
    # 6.4 — encrypted entry
    # ------------------------------------------------------------------
    def test_encrypted_entry(self):
        """An encrypted ZIP entry must be rejected."""
        members = _read_valid_members()
        data = _build_zip(members)
        # zipfile reads flag_bits from the CENTRAL DIRECTORY entry, not the
        # local file header.  The central directory signature is PK\x01\x02
        # and the general-purpose bit flag is at offset 8 in each record.
        raw = bytearray(data)
        sig = b"\x50\x4b\x01\x02"
        pos = 0
        while True:
            idx = raw.find(sig, pos)
            if idx == -1:
                break
            flag_offset = idx + 8
            raw[flag_offset] |= 0x1
            pos = idx + 4
        result = validate_bundle(bytes(raw))
        self.assertFalse(result["valid"])
        self.assertTrue(any("encrypted" in e for e in result["errors"]))

    # ------------------------------------------------------------------
    # 6.4 — directory entry
    # ------------------------------------------------------------------
    def test_directory_entry(self):
        """A directory entry must be rejected."""
        members = _read_valid_members()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in members.items():
                info = zipfile.ZipInfo(filename=name)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                zf.writestr(info, data)
            # Add a directory entry.
            dir_info = zipfile.ZipInfo(filename="subdir/")
            dir_info.compress_type = zipfile.ZIP_STORED
            dir_info.external_attr = 0o40755 << 16  # directory
            zf.writestr(dir_info, b"")
        result = validate_bundle(buf.getvalue())
        self.assertFalse(result["valid"])
        self.assertTrue(any("directory" in e for e in result["errors"]))

    # ------------------------------------------------------------------
    # 6.4 — absolute path
    # ------------------------------------------------------------------
    def test_absolute_path(self):
        """A member with an absolute path (/etc/passwd) must be rejected."""
        members = _read_valid_members()
        members["/etc/passwd"] = b"root:x:0:0:root:/root:/bin/bash"
        data = _build_zip(members)
        result = validate_bundle(data)
        self.assertFalse(result["valid"])
        self.assertTrue(any("absolute" in e for e in result["errors"]))

    # ------------------------------------------------------------------
    # 6.4 — ../ traversal
    # ------------------------------------------------------------------
    def test_dotdot_traversal(self):
        """A member with ../ in its path must be rejected."""
        members = _read_valid_members()
        members["../evil.txt"] = b"traversal"
        data = _build_zip(members)
        result = validate_bundle(data)
        self.assertFalse(result["valid"])
        self.assertTrue(any("traversal" in e or ".." in e for e in result["errors"]))

    # ------------------------------------------------------------------
    # 6.4 — backslash traversal
    # ------------------------------------------------------------------
    def test_backslash_traversal(self):
        """A member with backslash in its path must be rejected."""
        members = _read_valid_members()
        members["..\\evil.txt"] = b"backslash traversal"
        data = _build_zip(members)
        result = validate_bundle(data)
        self.assertFalse(result["valid"])
        self.assertTrue(
            any("backslash" in e or "traversal" in e or "unknown" in e for e in result["errors"])
        )

    # ------------------------------------------------------------------
    # 6.4 — unknown file
    # ------------------------------------------------------------------
    def test_unknown_file(self):
        """A member with an unknown name must be rejected."""
        members = _read_valid_members()
        members["evil.txt"] = b"not an AccessDoc member"
        data = _build_zip(members)
        result = validate_bundle(data)
        self.assertFalse(result["valid"])
        self.assertTrue(any("unknown member" in e for e in result["errors"]))

    # ------------------------------------------------------------------
    # 6.4 — missing required file
    # ------------------------------------------------------------------
    def test_missing_required_file(self):
        """A bundle missing a required member must be rejected."""
        members = _read_valid_members()
        del members["report.pdf"]
        # Rebuild manifest without report.pdf.
        core = {n: d for n, d in members.items()
                if n not in ("manifest.json", "attestation.intoto.json")}
        core["attestation.intoto.json"] = _valid_attestation_for(core)
        core["manifest.json"] = _valid_manifest_for(core)
        data = _build_zip(core)
        result = validate_bundle(data)
        self.assertFalse(result["valid"])
        self.assertTrue(any("missing" in e for e in result["errors"]))

    # ------------------------------------------------------------------
    # 6.4 — malformed digest
    # ------------------------------------------------------------------
    def test_malformed_digest(self):
        """A manifest entry with a non-hex sha256 must be rejected."""
        members = _read_valid_members()
        files = []
        for name, data in members.items():
            if name == "manifest.json":
                continue
            if name == "report.pdf":
                files.append((name, "NOT_VALID_HEX"))
            else:
                files.append((name, _sha256(data)))
        members["manifest.json"] = _make_manifest(files)
        data = _build_zip(members)
        result = validate_bundle(data)
        self.assertFalse(result["valid"])
        self.assertTrue(any("sha256" in e.lower() and "hex" in e.lower()
                            for e in result["errors"]))

    # ------------------------------------------------------------------
    # 6.4 — wrong manifest schema
    # ------------------------------------------------------------------
    def test_wrong_manifest_schema(self):
        """A manifest with an unsupported schema_version must be rejected."""
        members = _read_valid_members()
        manifest = json.loads(members["manifest.json"])
        manifest["schema_version"] = "9.9"
        members["manifest.json"] = json.dumps(manifest, indent=2).encode()
        data = _build_zip(members)
        result = validate_bundle(data)
        self.assertFalse(result["valid"])
        self.assertTrue(any("schema_version" in e for e in result["errors"]))

    # ------------------------------------------------------------------
    # 6.4 — extra attestation subject
    # ------------------------------------------------------------------
    def test_extra_attestation_subject(self):
        """An attestation with an extra subject must be rejected."""
        members = _read_valid_members()
        # Decode the attestation, add an extra subject, re-encode.
        envelope = json.loads(members["attestation.intoto.json"])
        statement = json.loads(base64.b64decode(envelope["payload"]))
        statement["subject"].append({
            "name": "evil-extra.txt",
            "digest": {"sha256": _sha256(b"evil")},
        })
        envelope["payload"] = base64.b64encode(
            json.dumps(statement).encode()
        ).decode()
        members["attestation.intoto.json"] = json.dumps(envelope, indent=2).encode()
        data = _build_zip(members)
        result = validate_bundle(data)
        self.assertFalse(result["valid"])
        self.assertTrue(any("extra subject" in e for e in result["errors"]))

    # ------------------------------------------------------------------
    # 6.4 — missing attestation subject
    # ------------------------------------------------------------------
    def test_missing_attestation_subject(self):
        """An attestation missing a subject must be rejected."""
        members = _read_valid_members()
        envelope = json.loads(members["attestation.intoto.json"])
        statement = json.loads(base64.b64decode(envelope["payload"]))
        # Remove one subject.
        statement["subject"] = [s for s in statement["subject"]
                                if s["name"] != "report.pdf"]
        envelope["payload"] = base64.b64encode(
            json.dumps(statement).encode()
        ).decode()
        members["attestation.intoto.json"] = json.dumps(envelope, indent=2).encode()
        data = _build_zip(members)
        result = validate_bundle(data)
        self.assertFalse(result["valid"])
        self.assertTrue(any("missing subject" in e for e in result["errors"]))

    # ------------------------------------------------------------------
    # 6.4 — too many members
    # ------------------------------------------------------------------
    def test_too_many_members(self):
        """A ZIP with more than MAX_MEMBER_COUNT entries must be rejected."""
        members = _read_valid_members()
        # Add enough unknown members to exceed the limit.
        for i in range(MAX_MEMBER_COUNT + 1):
            members[f"extra_{i}.txt"] = b"x" * 10
        data = _build_zip(members)
        result = validate_bundle(data)
        self.assertFalse(result["valid"])
        self.assertTrue(any("too many members" in e for e in result["errors"]))

    # ------------------------------------------------------------------
    # 6.4 — oversized member
    # ------------------------------------------------------------------
    def test_oversized_member(self):
        """A member exceeding MAX_MEMBER_EXPANDED_BYTES must be rejected."""
        members = _read_valid_members()
        # Replace report.pdf with a payload just over the limit.
        # Use highly compressible data so the compressed archive stays
        # under MAX_COMPRESSED_INPUT_BYTES (the check runs first).
        big = b"\x00" * (MAX_MEMBER_EXPANDED_BYTES + 1024)
        members["report.pdf"] = big
        core = {n: d for n, d in members.items()
                if n not in ("manifest.json", "attestation.intoto.json")}
        core["attestation.intoto.json"] = _valid_attestation_for(core)
        core["manifest.json"] = _valid_manifest_for(core)
        data = _build_zip(core)
        result = validate_bundle(data)
        self.assertFalse(result["valid"])
        self.assertTrue(
            any("expanded size" in e or "total expanded" in e
                or "compression ratio" in e
                for e in result["errors"]),
            msg=result["errors"],
        )


if __name__ == "__main__":
    unittest.main()
