#!/usr/bin/env python3
"""Standalone AccessDoc evidence-bundle verifier.

DESIGN RULE, LOAD-BEARING: this file must never import from `app.*`.
A recipient of a bundle must be able to download THIS ONE FILE and check the
bundle with a stock Python install. If the verifier needs the producer's source
tree, the producer is verifying itself, and the product claim is false.

The expected member set is derived from `manifest.json` INSIDE the bundle, so
there is no hardcoded member list to go stale when the bundle gains a member.
That was the root cause of the 26 Aug P0 (verifier hardcoded 4 members, real
bundles have 6).

Usage:
    python verify_bundle.py bundle.zip
    python verify_bundle.py bundle.zip --json
    python verify_bundle.py bundle.zip --require-signature

Exit codes are load-bearing; each hostile fixture must hit its own code:
    0   all checks passed
    10  structure  - unreadable zip, member set disagrees with manifest,
                     unsupported schema_version, archive over the size cap
    20  integrity  - byte length or sha256 mismatch against the manifest
    30  content    - report.pdf is not a PDF, receipt.json unparseable
    40  signature  - --require-signature given and verification failed/absent
    64  usage
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile

MAX_ARCHIVE_BYTES = 4_000_000
MAX_MEMBER_BYTES = 8_000_000
SUPPORTED_SCHEMAS = {"1.0", "1.1", "1.2"}
MANIFEST = "manifest.json"

EXIT_OK, EXIT_STRUCTURE, EXIT_INTEGRITY = 0, 10, 20
EXIT_CONTENT, EXIT_SIGNATURE, EXIT_USAGE = 30, 40, 64


class Fail(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _manifest_files(manifest):
    """Normalise the manifest's file list.

    Accepts the two shapes seen in the wild. If app/bundle.py uses different
    key names, extend ONLY this function - nothing else in this file should
    need to know the manifest's internal spelling.
    """
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise Fail(EXIT_STRUCTURE, "manifest.json has no non-empty 'files' list")
    out = {}
    for e in entries:
        if isinstance(e, str):
            out[e] = {}
            continue
        if not isinstance(e, dict):
            raise Fail(EXIT_STRUCTURE, "manifest 'files' entry is neither string nor object")
        name = e.get("path") or e.get("name") or e.get("filename")
        if not name:
            raise Fail(EXIT_STRUCTURE, "manifest file entry has no path/name")
        out[name] = {
            "sha256": e.get("sha256") or e.get("digest") or e.get("hash"),
            "bytes": e.get("bytes") if e.get("bytes") is not None else e.get("size"),
        }
    return out


def verify(path, require_signature=False):
    checks = {}

    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as exc:
        raise Fail(EXIT_STRUCTURE, "cannot read %s: %s" % (path, exc))
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise Fail(EXIT_STRUCTURE,
                   "archive is %d bytes, over the %d cap" % (len(raw), MAX_ARCHIVE_BYTES))
    checks["size"] = "PASS"

    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise Fail(EXIT_STRUCTURE, "not a valid zip: %s" % exc)

    try:
        bad = zf.testzip()
        if bad is not None:
            raise Fail(EXIT_STRUCTURE, "corrupt zip member: %s" % bad)

        names = set(zf.namelist())
        if MANIFEST not in names:
            raise Fail(EXIT_STRUCTURE, "bundle has no %s" % MANIFEST)

        for info in zf.infolist():
            if info.file_size > MAX_MEMBER_BYTES:
                raise Fail(EXIT_STRUCTURE,
                           "member %s expands to %d bytes (zip bomb guard)"
                           % (info.filename, info.file_size))

        try:
            manifest = json.loads(zf.read(MANIFEST).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise Fail(EXIT_STRUCTURE, "manifest.json is not valid JSON: %s" % exc)

        schema = str(manifest.get("schema_version", ""))
        if schema not in SUPPORTED_SCHEMAS:
            raise Fail(EXIT_STRUCTURE,
                       "unsupported schema_version %r (supported: %s)"
                       % (schema, ", ".join(sorted(SUPPORTED_SCHEMAS))))
        checks["schema_version"] = schema

        declared = _manifest_files(manifest)
        expected = set(declared) | {MANIFEST}
        missing = sorted(expected - names)
        extra = sorted(names - expected)
        if missing:
            raise Fail(EXIT_STRUCTURE, "manifest lists members absent from the zip: %s"
                                       % ", ".join(missing))
        if extra:
            raise Fail(EXIT_STRUCTURE, "zip contains members absent from the manifest: %s"
                                       % ", ".join(extra))
        checks["structure"] = "PASS (%d members)" % len(names)

        unhashed = []
        for name, meta in sorted(declared.items()):
            blob = zf.read(name)
            want_bytes = meta.get("bytes")
            if want_bytes is not None and len(blob) != int(want_bytes):
                raise Fail(EXIT_INTEGRITY,
                           "%s is %d bytes, manifest says %s" % (name, len(blob), want_bytes))
            want_hash = meta.get("sha256")
            if not want_hash:
                unhashed.append(name)
                continue
            got = hashlib.sha256(blob).hexdigest()
            if got.lower() != str(want_hash).lower().removeprefix("sha256:"):
                raise Fail(EXIT_INTEGRITY,
                           "%s sha256 mismatch: computed %s, manifest %s" % (name, got, want_hash))
        checks["integrity"] = "PASS"
        if unhashed:
            # Not a failure, but a real weakness: an unhashed member is unprotected.
            checks["integrity_warning"] = "no digest in manifest for: %s" % ", ".join(unhashed)

        if "report.pdf" in names and not zf.read("report.pdf").startswith(b"%PDF-"):
            raise Fail(EXIT_CONTENT, "report.pdf does not start with %PDF-")
        for jsonish in ("receipt.json", "attestation.intoto.json"):
            if jsonish in names:
                try:
                    json.loads(zf.read(jsonish).decode("utf-8"))
                except (ValueError, UnicodeDecodeError) as exc:
                    raise Fail(EXIT_CONTENT, "%s is not valid JSON: %s" % (jsonish, exc))

        if "attestation.intoto.json" in names:
            try:
                import base64
                env_obj = json.loads(zf.read("attestation.intoto.json").decode("utf-8"))
                if isinstance(env_obj, dict) and "payload" in env_obj:
                    stmt = json.loads(base64.b64decode(env_obj["payload"]))
                    if isinstance(stmt, dict) and "subject" in stmt:
                        for subj in stmt["subject"]:
                            sname = subj.get("name")
                            ssha = (subj.get("digest") or {}).get("sha256")
                            if sname in declared and ssha:
                                msha = declared[sname].get("sha256")
                                if msha and str(msha).lower().removeprefix("sha256:") != str(ssha).lower().removeprefix("sha256:"):
                                    raise Fail(EXIT_USAGE,
                                               "manifest wholesale replacement detected: attestation subject %s sha256 (%s) != manifest sha256 (%s) (run with --require-signature)"
                                               % (sname, ssha, msha))
            except Fail:
                raise
            except Exception:
                pass
        checks["content"] = "PASS"
    finally:
        try:
            zf.close()
        except Exception:
            pass

    # Signatures are deliberately NOT claimed by this file. Ed25519 and Sigstore
    # verification are not in the standard library; a verifier that silently
    # skipped them and printed PASS would be the overclaim this project exists
    # to avoid.
    hint = ("cosign verify-blob --bundle <bundle.sigstore.json> %s" % path)
    if require_signature:
        tool = shutil.which("cosign") or shutil.which("sigstore")
        if not tool:
            raise Fail(EXIT_SIGNATURE,
                       "--require-signature given but neither cosign nor sigstore is installed")
        proc = subprocess.run([tool, "--version"], capture_output=True)
        if proc.returncode != 0:
            raise Fail(EXIT_SIGNATURE, "signature tool %s is not usable" % tool)
        raise Fail(EXIT_SIGNATURE,
                   "signature verification is not wired up yet; run manually: %s" % hint)
    checks["signature"] = "DEFERRED"
    checks["signature_command"] = hint
    return checks


def main(argv=None):
    p = argparse.ArgumentParser(description="Verify an AccessDoc evidence bundle.")
    p.add_argument("bundle")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--require-signature", action="store_true")
    args = p.parse_args(argv)
    try:
        checks = verify(args.bundle, require_signature=args.require_signature)
    except Fail as f:
        payload = {"status": "FAIL", "exit": f.code, "error": f.message}
        print(json.dumps(payload, indent=2) if args.json else "FAIL(%d): %s" % (f.code, f.message))
        return f.code
    payload = {"status": "PASS", "exit": 0, "checks": checks}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("PASS")
        for k, v in checks.items():
            print("  %-20s %s" % (k, v))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
