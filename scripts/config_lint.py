"""Config lint: parse each config file the way its real consumer parses it.

Uses strict utf-8 (not utf-8-sig) — identical to what Vercel, ajv, and
Python's json.load use.  A UTF-8 BOM that slips through bom_lint.py will
be caught here with a clear parse error.
"""
import json
import pathlib
import sys

CONFIGS = [
    "vercel.json",
    "schemas/openacr-0.1.0.json",
    "fixtures/axe-sample.json",
]

fail = False
for t in CONFIGS:
    p = pathlib.Path(t)
    if not p.exists():
        continue
    try:
        # Strict: decode as utf-8, then parse — same as Vercel's validator.
        # Do NOT use utf-8-sig here; that would silently swallow a BOM.
        json.loads(p.read_bytes().decode("utf-8"))
        print(f"ok: {t}")
    except Exception as e:
        print(f"FAIL: {t}: {e}")
        fail = True

sys.exit(1 if fail else 0)
