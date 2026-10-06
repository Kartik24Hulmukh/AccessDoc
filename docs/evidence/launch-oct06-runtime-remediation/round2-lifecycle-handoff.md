# API lifecycle causal fix — owned source frozen

Owned files only: `api/handler.py`, new `tests/test_vercel_runtime_lifecycle.py`. No Docker/compose/hosting, reporter, OTLP source/test or main-admission edits. No commit, stage, push, deployment, provider calls, secret reads or billing action. Lead owns combined commit/full suite/exact-head CI and protected hosted revalidation.

## Cause and correction

Archived live original preview trace establishes Vercel replaces `handle_one_request`, dispatching GET through `handle_request` directly; our old initialization was bypassed and static response accessed missing `request_id`. This is a runtime lifecycle bug, not missing deployed dependencies.

Implemented one reentrant request-scope owner shared by stdlib parser envelope and actual HTTP methods. All supported do_* boundaries initialize before response/body/auth work when runtime bypasses the envelope. Nested HEAD->GET shares scope. Decorated `send_error` covers runtime parse/unsupported dispatch. Stdlib still initializes before parsing and resets stale keepalive parse fields, preventing idle phantom requests. Runtime parse rejection without a parsed command clears absent/stale path/headers. One owner finalizes request/error counters, finite-route private log and SERVER span exactly once, with finally-cleared thread trace, cached context and active flag. Existing telemetry/export budget, auth/admission and public-body policy unchanged.

## Preserved causal and acceptance receipts

- `/data/accessdoc-evidence/round2-preview-failure-redacted.txt`: original live failure supplied by lead.
- `round2-lifecycle-before.txt`: new browser/static regression failed on **both** runtime dispatch mimics before source fix (missing request_id; two subtest errors). Retained, not rewritten.
- `round2-lifecycle-after.txt`: initial 4-test success before expanded teardown/error/idle coverage; not final-source receipt.
- `round2-lifecycle-focused.txt`: earlier 49 tests passed in16.881s before small runtime malformed-parser enhancement; not final-source receipt.
- `round2-lifecycle-final.txt`: final dedicated **6 tests passed in0.328s** under ResourceWarning-as-error. Includes inline/delegated runtime overrides that parse and dispatch without invoking our handler envelope, standard parser, real loopback requests, unique IDs/root traces, inbound-parent propagation/reset, keepalive, nested HEAD, OPTIONS, auth errors, valid deterministic bundle, disabled remediation, malformed/unsupported requests, exception privacy, finite routes, exact counters/logs/SERVER spans and teardown. Mocked span sink intentionally prevents collector calls.
- `round2-lifecycle-browser.txt`: **real existing Chromium** against both runtime mimics: document, app.css, app.js and favicon each200; four requests/exactly four completions/logs/SERVER calls per mimic; state cleared. Browser routes confined to numeric loopback, no credential/provider service. This is local browser validation, not hosted smoke.
- `round2-lifecycle-final-focused.txt`: **57 tests passed in18.608s**, ResourceWarning-as-error, using existing `/data/accessdoc-venv/bin/python`, `-B`, cleared environment. Dedicated lifecycle plus auth config, hosted boundary/metrics/UI/surface/admission/lifecycle and stdlib error contracts. Overlapping counts must not be added together.
- Earlier `/data/accessdoc-round2-offline-check.txt` default-Python `aiohttp` import error remains distinct and retained. Correct installed interpreter receipts already show successful offline and real-loopback adapter checks; this does not explain the live Vercel failure.

## Frozen owned hashes

- api/handler.py: `1c1a3d489ac634d0efb83b243cadf8457e375c35b61335f5519feaaecb606b56`
- tests/test_vercel_runtime_lifecycle.py: `7c6324e7238ad756a2330791bbb95df2fc9ebfecfb5da115fad1f381e4ec702e`

`git diff --check -- api/handler.py` passed. Owned source now frozen: no further edits until lead requests. Existing live original preview remains failed; production is old main per lead. Account/env metadata does not prove configured private auth, required operation controls or useful functional acceptance. No remediation/model calls or human assent inferred. Source candidate only; continued production HOLD until final-source CI and protected exact-target acceptance.
