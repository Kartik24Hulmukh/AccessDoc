# One-page accessibility evidence handoff

This uses the existing Playwright scanner, **pinned local axe-core 4.11.0**,
AccessDoc bundle generator, and verifier. It is a supervised handoff for an
authorized page, not a whole-site audit or a conformance claim.

From a checkout with Python and Node installed:

```sh
python -m pip install -r requirements.txt playwright
python -m playwright install chromium
npm install --no-save --no-package-lock axe-core@4.11.0
export ACCESSDOC_AXE_PATH="$PWD/node_modules/axe-core/axe.min.js"
mkdir -p /tmp/accessdoc-handoff
python cli.py scan https://your-authorized-public-page.example/path \
  --out /tmp/accessdoc-handoff/axe.json
python cli.py bundle /tmp/accessdoc-handoff/axe.json \
  --client-name "Example client" --audit-date 2026-09-29 \
  --sarif --vpat --eaa --out /tmp/accessdoc-handoff/bundle.zip
python cli.py verify /tmp/accessdoc-handoff/bundle.zip
```

Replace the example URL with a page you are **authorized** to test; do not
copy that placeholder into an automated job. Private/loopback targets require
an explicit local `--allow-private-network` opt-in, never an untrusted URL. Do
not run this against public production sites at load. For authenticated or
interactive states, run axe within your own authorized Playwright test and
pass its *full* result JSON to `bundle` instead; do not hand AccessDoc login
credentials or pretend that an initial-page scan covers later states.

Before giving the packet to a client, record outside the generated bundle:
the exact route and state reached, viewport, authentication context (without
secrets), scan time, consent, areas **not tested**, manual/assistive-technology
checks, reviewer, and requested corrections. The receipt carries the scanner
URL, engine version and found targets; it does **not** authenticate the browser
state, prove a real human review, or attest that the scan was truthful.
`verify` checks bundle integrity, not scanner completeness or legal acceptance.
Share `report.html` as the accessible primary artifact; the PDF is untagged.

For a paid-pilot decision, observe a practitioner preparing this handoff from
a real, consented engagement and a recipient acting on it. Measure editing
time, corrections, acceptance, and whether a **second** handoff is requested.
No synthetic test substitutes for those outcomes.