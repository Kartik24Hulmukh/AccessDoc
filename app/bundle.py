"""Build and validate the AccessDoc evidence ZIP bundle.

Default (core) members, in order:
  report.pdf, report.html, receipt.json, openacr.yaml,
  attestation.intoto.json, manifest.json

Optional members (added only when requested) are inserted before the
attestation so they are attested too:
  findings.sarif.json, vpat-draft.html, eaa-evidence.md, trend.json

manifest.json is ALWAYS last and attests every other member.
MEMBERS is the canonical order for the default (no-optional) bundle.
"""
import base64
import hashlib
import json
import re
import zipfile
from io import BytesIO

# Canonical default bundle order (backward compatible with v0.5).
MEMBERS = (
    "report.pdf",
    "report.html",
    "receipt.json",
    "openacr.yaml",
    "attestation.intoto.json",
    "manifest.json",
)

# Members that must always be present in any valid bundle.
CORE_REQUIRED = (
    "report.pdf",
    "report.html",
    "receipt.json",
    "openacr.yaml",
    "attestation.intoto.json",
    "manifest.json",
)

# Every member name that may legally appear in an AccessDoc bundle.
ALLOWED_MEMBER_NAMES = frozenset({
    "report.pdf",
    "report.html",
    "receipt.json",
    "openacr.yaml",
    "attestation.intoto.json",
    "manifest.json",
    "findings.sarif.json",
    "vpat-draft.html",
    "eaa-evidence.md",
    "trend.json",
    "due-diligence.md",
})

SCHEMA_VERSION = "1.1"
SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0", "1.1"})
MAX_BUNDLE_BYTES = 8_000_000

# --- Hostile-ZIP hardening limits -------------------------------------------
# All limits are checked BEFORE any member content is read so a hostile
# archive cannot exhaust resources by forcing decompression.
MAX_COMPRESSED_INPUT_BYTES = 10 * 1024 * 1024   # 10 MiB total archive size
MAX_MEMBER_COUNT = 20                            # maximum number of entries
MAX_MEMBER_EXPANDED_BYTES = 16 * 1024 * 1024    # 16 MiB per member
MAX_TOTAL_EXPANDED_BYTES = 32 * 1024 * 1024     # 32 MiB across all members
MAX_COMPRESSION_RATIO = 100                      # expanded:compressed
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


# Fixed timestamp for every ZIP entry (1980-01-01, the ZIP format epoch).
# Chosen because it is the earliest value the format can represent.
FIXED_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def build_bundle(artifacts):
    # Ordered payloads (everything except manifest.json).
    payloads = artifacts.payloads()

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "files": [
            {"path": name, "sha256": _sha256(data)}
            for name, data in payloads.items()
        ],
    }
    payloads["manifest.json"] = json.dumps(manifest, indent=2).encode()

    # Reproducibility: zipfile.writestr() stamps each entry with the CURRENT
    # time, so two runs of identical input produced different archive bytes.
    # Every entry is pinned to a fixed epoch and fixed external attributes so
    # the archive is a pure function of its contents.
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in payloads.items():
            info = zipfile.ZipInfo(filename=name, date_time=FIXED_ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            info.create_system = 3  # unix, so the host OS cannot leak in
            zf.writestr(info, data)

    data = buf.getvalue()
    if len(data) > MAX_BUNDLE_BYTES:
        raise ValueError(f"Bundle too large: {len(data)} bytes")
    return data


# ---------------------------------------------------------------------------
# Hostile-ZIP hardened validation
# ---------------------------------------------------------------------------

def _validate_zip_structure(zip_bytes):
    """Phase 6.1 — structural checks that need NO content reads.

    Returns (zipfile.ZipFile_or_None, errors_list).
    The ZipFile is opened but NO member content is read here.
    """
    errors = []

    # 6.1a — maximum compressed input size (before even opening).
    if len(zip_bytes) > MAX_COMPRESSED_INPUT_BYTES:
        errors.append(
            f"archive too large: {len(zip_bytes)} > {MAX_COMPRESSED_INPUT_BYTES}"
        )
        return None, errors

    try:
        zf = zipfile.ZipFile(BytesIO(zip_bytes))
    except Exception as exc:
        errors.append(f"not a valid zip: {exc}")
        return None, errors

    infos = zf.infolist()

    # 6.1b — maximum member count.
    if len(infos) > MAX_MEMBER_COUNT:
        errors.append(
            f"too many members: {len(infos)} > {MAX_MEMBER_COUNT}"
        )

    seen_names = set()
    total_compressed = 0
    total_expanded = 0

    for info in infos:
        name = info.filename

        # 6.1c — unique member names (no duplicates).
        if name in seen_names:
            errors.append(f"duplicate member name: {name!r}")
        seen_names.add(name)

        # 6.1d — no directory entries.
        if info.is_dir():
            errors.append(f"directory entry not allowed: {name!r}")

        # 6.1e — no encrypted members (general-purpose bit flag bit 0).
        if info.flag_bits & 0x1:
            errors.append(f"encrypted member not allowed: {name!r}")

        # 6.1f — no absolute paths.
        if name.startswith("/"):
            errors.append(f"absolute path not allowed: {name!r}")

        # 6.1g — no .. traversal.
        if ".." in name.split("/"):
            errors.append(f"path traversal (..) not allowed: {name!r}")

        # 6.1h — no backslash path ambiguity.
        if "\\" in name:
            errors.append(f"backslash in path not allowed: {name!r}")

        # 6.1i — no null bytes in names.
        if "\x00" in name:
            errors.append(f"null byte in member name: {name!r}")

        # 6.1j — only known AccessDoc member names.
        if name not in ALLOWED_MEMBER_NAMES:
            errors.append(f"unknown member name: {name!r}")

        # Size accounting for bomb / ratio detection.
        comp = info.compress_size
        exp = info.file_size
        total_compressed += comp
        total_expanded += exp

        # 6.1k — maximum individual expanded size.
        if exp > MAX_MEMBER_EXPANDED_BYTES:
            errors.append(
                f"{name!r}: expanded size {exp} > {MAX_MEMBER_EXPANDED_BYTES}"
            )

        # 6.1l — maximum compression ratio per member.
        if comp > 0 and exp > 0:
            ratio = exp / comp
            if ratio > MAX_COMPRESSION_RATIO:
                errors.append(
                    f"{name!r}: compression ratio {ratio:.1f}:1 > "
                    f"{MAX_COMPRESSION_RATIO}:1"
                )

    # 6.1m — maximum total expanded size.
    if total_expanded > MAX_TOTAL_EXPANDED_BYTES:
        errors.append(
            f"total expanded size {total_expanded} > "
            f"{MAX_TOTAL_EXPANDED_BYTES}"
        )

    # 6.1n — manifest.json exactly once.
    manifest_count = sum(1 for i in infos if i.filename == "manifest.json")
    if manifest_count == 0:
        errors.append("manifest.json missing")
    elif manifest_count > 1:
        errors.append(f"manifest.json appears {manifest_count} times")

    if errors:
        zf.close()
        return None, errors

    return zf, errors


def _validate_manifest(zf, names):
    """Phase 6.2 — manifest structure and type validation."""
    errors = []
    try:
        manifest = json.loads(zf.read("manifest.json"))
    except Exception as exc:
        return errors + [f"manifest.json unreadable: {exc}"], None, None

    # 6.2a — root object.
    if not isinstance(manifest, dict):
        errors.append("manifest root is not an object")
        return errors, None, None

    # 6.2b — supported schema version.
    sv = manifest.get("schema_version")
    if sv not in SUPPORTED_SCHEMA_VERSIONS:
        errors.append(
            f"manifest schema_version {sv!r} not in "
            f"{sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )

    # 6.2c — files is a list.
    files = manifest.get("files")
    if not isinstance(files, list):
        errors.append("manifest 'files' is not a list")
        return errors, None, None

    manifest_paths = []
    manifest_map = {}

    for idx, entry in enumerate(files):
        # 6.2d — each entry is an object.
        if not isinstance(entry, dict):
            errors.append(f"manifest files[{idx}] is not an object")
            continue

        path = entry.get("path")
        sha = entry.get("sha256")

        # 6.2e — path is non-empty allowed string.
        if not isinstance(path, str) or not path:
            errors.append(f"manifest files[{idx}]: path missing or not string")
            continue
        if path not in ALLOWED_MEMBER_NAMES:
            errors.append(f"manifest files[{idx}]: path {path!r} not allowed")

        # 6.2f — sha256 is exactly 64 lowercase hex.
        if not isinstance(sha, str) or not _HEX64_RE.match(sha):
            errors.append(
                f"manifest files[{idx}] ({path!r}): sha256 not 64 lowercase hex"
            )

        manifest_paths.append(path)
        manifest_map[path] = sha

    # 6.2g — no duplicate manifest paths.
    dup_check = set()
    for p in manifest_paths:
        if p in dup_check:
            errors.append(f"duplicate manifest path: {p!r}")
        dup_check.add(p)

    # 6.2h — no manifest entry for manifest.json.
    if "manifest.json" in manifest_map:
        errors.append("manifest.json must not appear in manifest files list")

    # 6.2i — manifest membership matches ZIP membership exactly.
    zip_non_manifest = {n for n in names if n != "manifest.json"}
    manifest_set = set(manifest_paths)
    if zip_non_manifest != manifest_set:
        only_zip = zip_non_manifest - manifest_set
        only_manifest = manifest_set - zip_non_manifest
        if only_zip:
            errors.append(f"in ZIP but not manifest: {sorted(only_zip)}")
        if only_manifest:
            errors.append(f"in manifest but not ZIP: {sorted(only_manifest)}")

    return errors, manifest_map, manifest


def _validate_attestation(zf, manifest_map):
    """Phase 6.3 — attestation structure validation."""
    from .intoto import PAYLOAD_TYPE, STATEMENT_TYPE

    errors = []
    try:
        envelope = json.loads(zf.read("attestation.intoto.json"))
    except Exception as exc:
        return errors + [f"attestation.intoto.json unreadable: {exc}"]

    if not isinstance(envelope, dict):
        errors.append("attestation root is not an object")
        return errors

    # 6.3a — expected payload type.
    pt = envelope.get("payloadType")
    if pt != PAYLOAD_TYPE:
        errors.append(
            f"attestation payloadType {pt!r} != expected {PAYLOAD_TYPE!r}"
        )

    # 6.3b — decodable payload.
    payload_b64 = envelope.get("payload")
    if not isinstance(payload_b64, str):
        errors.append("attestation payload missing or not string")
        return errors
    try:
        statement = json.loads(base64.b64decode(payload_b64))
    except Exception as exc:
        errors.append(f"attestation payload not decodable: {exc}")
        return errors

    if not isinstance(statement, dict):
        errors.append("attestation statement is not an object")
        return errors

    # 6.3c — in-toto statement type.
    stype = statement.get("_type")
    if stype != STATEMENT_TYPE:
        errors.append(
            f"attestation _type {stype!r} != expected {STATEMENT_TYPE!r}"
        )

    subjects = statement.get("subject")
    if not isinstance(subjects, list):
        errors.append("attestation subject is not a list")
        return errors

    subject_names = []
    subject_map = {}
    for idx, s in enumerate(subjects):
        if not isinstance(s, dict):
            errors.append(f"attestation subject[{idx}] is not an object")
            continue
        sname = s.get("name")
        if not isinstance(sname, str) or not sname:
            errors.append(f"attestation subject[{idx}]: name missing")
            continue
        subject_names.append(sname)
        digests = s.get("digest", {})
        sha = digests.get("sha256") if isinstance(digests, dict) else None
        subject_map[sname] = sha

    # 6.3d — no duplicate subject names.
    seen_subj = set()
    for sn in subject_names:
        if sn in seen_subj:
            errors.append(f"duplicate attestation subject: {sn!r}")
        seen_subj.add(sn)

    # 6.3e — subject membership matches expected files.
    # The attestation attests every manifest entry EXCEPT itself
    # (attestation.intoto.json) — an envelope cannot meaningfully attest
    # its own bytes.
    expected = {n for n in manifest_map.keys()
                if n != "attestation.intoto.json"}
    actual = set(subject_names)
    if expected != actual:
        missing = expected - actual
        extra = actual - expected
        if missing:
            errors.append(f"attestation missing subjects: {sorted(missing)}")
        if extra:
            errors.append(f"attestation extra subjects: {sorted(extra)}")

    # 6.3f — subject digests match manifest digests.
    for name, expected_sha in manifest_map.items():
        if name == "attestation.intoto.json":
            continue  # not self-attested
        actual_sha = subject_map.get(name)
        if actual_sha is None:
            continue  # already reported via membership check
        if actual_sha != expected_sha:
            errors.append(
                f"attestation subject {name!r}: digest mismatch "
                f"(manifest={expected_sha}, attestation={actual_sha})"
            )

    return errors


def validate_bundle(zip_bytes):
    """Validate an AccessDoc evidence ZIP bundle with hostile-input hardening.

    Checks run in order of cheapest-to-verify → most-expensive so a hostile
    archive is rejected before any expensive decompression or JSON parsing.
    """
    errors = []

    # --- Phase 6.1: structural checks (no content reads) ---
    zf, struct_errors = _validate_zip_structure(zip_bytes)
    errors.extend(struct_errors)
    if zf is None:
        return {"valid": False, "errors": errors}

    try:
        names = zf.namelist()

        # Required members present.
        for required in CORE_REQUIRED:
            if required not in names:
                errors.append(f"required member missing: {required}")

        if errors:
            return {"valid": False, "errors": errors}

        # --- Phase 6.2: manifest structure & types ---
        manifest_errors, manifest_map, _manifest = _validate_manifest(zf, names)
        errors.extend(manifest_errors)

        if errors:
            return {"valid": False, "errors": errors}

        # --- Phase 6.3: attestation structure ---
        attest_errors = _validate_attestation(zf, manifest_map)
        errors.extend(attest_errors)

        if errors:
            return {"valid": False, "errors": errors}

        # --- Content digest verification (only after all structural checks pass) ---
        for path, expected in manifest_map.items():
            if path not in names:
                errors.append(f"{path}: attested but absent")
                continue
            if _sha256(zf.read(path)) != expected:
                errors.append(f"{path}: digest mismatch")

        if errors:
            return {"valid": False, "errors": errors}

        # --- Phase 6.4: receipt self-consistency -------------------------
        # Digest checks prove the ZIP was not edited after generation. They do
        # NOT prove the receipt was internally honest when it was generated:
        # a receipt whose finding_fingerprint disagrees with its own rule /
        # source / target is either tampered-with-and-resealed or produced by
        # an incompatible generator. Either way it must not validate.
        from .receipt_validate import validate_receipt
        try:
            receipt = json.loads(zf.read("receipt.json"))
        except Exception as exc:
            errors.append(f"receipt.json unreadable: {exc}")
        else:
            errors.extend(
                f"receipt.json: {e}" for e in validate_receipt(receipt)
            )

    except Exception as exc:
        errors.append(f"Read error: {exc}")
    finally:
        try:
            zf.close()
        except Exception:
            pass

    return {"valid": len(errors) == 0, "errors": errors}
