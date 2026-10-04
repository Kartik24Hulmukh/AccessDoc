"""Local loopback pilot. No model credentials, no hosting purchase, no promotion.

Requires ACCESSDOC_API_KEY supplied privately via environment. Defaults to port
8000. This launcher is local evaluation only; see docs/ZERO_SPEND_PILOT.md.
"""
import os
import sys
from pathlib import Path

if __name__ == '__main__':
    if not os.environ.get('ACCESSDOC_API_KEY', '').strip():
        sys.exit('Set a fresh ACCESSDOC_API_KEY privately in the environment; refusing unauthenticated startup.')
    # Never allow inherited upstream credentials to create an accidental charge.
    os.environ.pop('MELIOUS_API_KEY', None)
    os.environ.pop('ACCESSDOC_API_KEYS', None)
    os.environ.update(HOST='127.0.0.1', ALLOW_NETWORK_EXPOSURE='false',
                      ACCESSDOC_REQUIRE_AUTH='true',
                      ACCESSDOC_GENERATION_ENABLED='true',
                      ACCESSDOC_REMEDIATION_ENABLED='false',
                      REPORT_TTL_SECONDS='1800')
    port = int(os.getenv('PORT', '8000'))
    if not 1 <= port <= 65535:
        sys.exit('PORT must be 1..65535')
    os.environ['ALLOWED_HOSTS'] = f'127.0.0.1:{port},localhost:{port}'
    os.environ['ALLOWED_ORIGINS'] = f'http://127.0.0.1:{port},http://localhost:{port}'
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    os.execv(sys.executable, [sys.executable, '-m', 'app.main'])
