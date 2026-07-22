"""Build and validate the AccessDoc ZIP bundle v1.1.\n\nBundle members (in order):\n  report.pdf, report.html, receipt.json, openacr.yaml,\n  attestation.intoto.json, manifest.json\n\nmanifest.json is ALWAYS last so MEMBERS[:-1] == all attested files.\n"""
import hashlib
import json
import zipfile
from io import BytesIO

MEMBERS = (
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
    payloads = {
        "report.pdf":              artifacts.pdf_bytes,
        "report.html":             artifacts.html_bytes,
        "receipt.json":            artifacts.receipt_json.encode(),
        "openacr.yaml":            artifacts.openacr_yaml.encode(),
        "attestation.intoto.json": artifacts.intoto_bytes,
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "files": [
            {"path": name, "sha256": _sha256(payloads[name])}
            for name in MEMBERS[:-1]
        ],
    }
    payloads["manifest.json"] = json.dumps(manifest, indent=2).encode()

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in MEMBERS:
            zf.writestr(name, payloads[name])

    data = buf.getvalue()
    if len(data) > MAX_BUNDLE_BYTES:
        raise ValueError(f"Bundle too large: {len(data)} bytes")
    return data


def validate_bundle(zip_bytes):
    errors = []
    try:
        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            if set(names) != set(MEMBERS):
                errors.append(f"Member mismatch: got {sorted(names)}, expected {sorted(MEMBERS)}")
                return {"valid": False, "errors": errors}
            manifest = json.loads(zf.read("manifest.json"))
            for entry in manifest.get("files", []):
                path, expected = entry["path"], entry["sha256"]
                if _sha256(zf.read(path)) != expected:
                    errors.append(f"{path}: digest mismatch")
    except Exception as exc:
        errors.append(f"Read error: {exc}")
    return {"valid": len(errors) == 0, "errors": errors}
