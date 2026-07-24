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
import hashlib
import json
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

SCHEMA_VERSION = "1.1"
MAX_BUNDLE_BYTES = 8_000_000


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

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in payloads.items():
            zf.writestr(name, data)

    data = buf.getvalue()
    if len(data) > MAX_BUNDLE_BYTES:
        raise ValueError(f"Bundle too large: {len(data)} bytes")
    return data


def validate_bundle(zip_bytes):
    errors = []
    try:
        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            if "manifest.json" not in names:
                return {"valid": False, "errors": ["manifest.json missing"]}
            for required in CORE_REQUIRED:
                if required not in names:
                    errors.append(f"required member missing: {required}")
            manifest = json.loads(zf.read("manifest.json"))
            attested = {e["path"]: e["sha256"] for e in manifest.get("files", [])}
            non_manifest = [n for n in names if n != "manifest.json"]
            if set(non_manifest) != set(attested):
                errors.append(
                    f"member/manifest mismatch: members={sorted(non_manifest)}, "
                    f"attested={sorted(attested)}"
                )
            for path, expected in attested.items():
                if path not in names:
                    errors.append(f"{path}: attested but absent")
                    continue
                if _sha256(zf.read(path)) != expected:
                    errors.append(f"{path}: digest mismatch")
    except Exception as exc:
        errors.append(f"Read error: {exc}")
    return {"valid": len(errors) == 0, "errors": errors}
