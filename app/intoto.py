"""in-toto v1 unsigned DSSE envelope for AccessDoc bundles."""
import base64
import datetime
import hashlib
import json
from .models import VERSION

PAYLOAD_TYPE = "application/vnd.in-toto+json"
PREDICATE_TYPE = "https://accessdoc.dev/attestation/evidence-receipt/v1"
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_statement(subjects, predicate):
    return {
        "_type": STATEMENT_TYPE,
        "subject": [
            {"name": name, "digest": {"sha256": _sha256(data)}}
            for name, data in sorted(subjects.items())
        ],
        "predicateType": PREDICATE_TYPE,
        "predicate": predicate,
    }


def build_dsse_envelope(statement):
    payload_bytes = json.dumps(statement, separators=(",", ":")).encode()
    return {
        "payloadType": PAYLOAD_TYPE,
        "payload": base64.b64encode(payload_bytes).decode(),
        "signatures": [],
    }


def build_intoto_bundle(file_payloads, extra_meta=None):
    predicate = {
        "buildType": "https://accessdoc.dev/build/v1",
        "generator": {"name": "accessdoc", "version": VERSION},
        "timestamp": _utc_now(),
        "materials": [
            {"uri": name, "digest": {"sha256": _sha256(data)}}
            for name, data in sorted(file_payloads.items())
        ],
    }
    if extra_meta:
        predicate.update(extra_meta)
    statement = build_statement(file_payloads, predicate)
    envelope  = build_dsse_envelope(statement)
    return json.dumps(envelope, indent=2).encode()


def verify_statement_subjects(statement, file_payloads):
    mismatches = []
    subject_map = {s["name"]: s["digest"]["sha256"] for s in statement.get("subject", [])}
    for name, data in file_payloads.items():
        expected = subject_map.get(name)
        if expected is None:
            mismatches.append(f"{name}: not in statement")
        elif expected != _sha256(data):
            mismatches.append(f"{name}: digest mismatch")
    return mismatches
