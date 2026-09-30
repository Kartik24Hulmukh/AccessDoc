# Reproduction and integrity

Read PROVENANCE.json before comparing sources. Original faults.py/repro.py require the before source, not the patched API. Final native-faults-final.py/repro-final.py require the final source. These frozen standalone harnesses use the original /data/AccessDoc path; set PYTHONPATH to your checkout if using another path. They send only synthetic loopback data (the final native DNS case replaces the resolver). Model benchmark requires an explicitly supplied secret environment and operator-approved egress; secrets are absent here. Live reports do not certify billing or sustained provider capacity.

Install requirements-dev.txt, local Playwright Chromium and pinned axe-core. Reproduce core regressions with python -m pytest tests -q; run scripts/verify_release.py for ten local gates. Final load/chaos scripts run against loopback only. Real protected-preview smoke requires authorized automation access and the exact final SHA.

Failed original and intermediate runs, Windows/evidence CI failures, and a failed obsolete TTL harness assumption are retained intentionally. repro-final-corrected.log/results-final.json fix the harness's assumption that an expired payload still exists; that is not a new product failure. Duplicate-ZIP warnings originate from intentionally hostile fixtures. File hashes are in MANIFEST.sha256.json; the manifest does not hash itself.
