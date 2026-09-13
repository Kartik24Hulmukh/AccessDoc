# September 13 continuation evidence

This folder records real local executions, not production capacity promises.
Base reviewed: `91ddbb9580a7eccdf2d93736113e1fe8af6a9445`.
Hosted backend source for the soak: PR #34 initial code (the run began before
request-log token redaction/read-timeout additions; those are covered by final tests).
Both 60-second stages used 8 workers and 100-instance axe evidence with auth.
All successful ZIPs validated; overload 503s are expected admission rejections.

| Adapter | Attempts | Valid 200 | Expected 503 | Successful bundles/s | Recovery |
|---|---:|---:|---:|---:|---|
| Serverless handler, local server | 6,804 | 2,619 | 4,185 | 43.63 | 200 |
| Self-hosted | 3,510 | 2,004 | 1,506 | 33.37 | 200 |

No corrupt ZIPs or transport errors were observed. RSS samples and successful
latency percentiles are in the JSON; memory/CPU include the local load driver
and in-process ZIP verifier, not just a deployed worker. Stages ran sequentially
in one process and sometimes concurrently with tests, so cross-stage comparisons
are not controlled benchmarks. 100x refers only to finding-instance count.

`hardening-load-current.json`: nine malformed/null contracts, 1-to-100 instance
scaling, 100 requests / 8 local slots; deterministic identical ZIPs, all pass.
`browser-check.json`: real Chromium sample-button -> generation -> downloaded
ZIP verified, no JS errors, axe UI audit. The initial audit found a nested aside
landmark; it was changed to a labeled group and retested. The authenticated
error/retry/download flow is additionally covered by `tests/test_hosted_ui.py`.
`axe-self-audit.json`: generated HTML report self-audit, zero axe violations.
`independent-openacr.txt`: generated sample validated with actual GSA upstream
CLI at the recorded commit; stdout was `Valid!`. This closes sample-level
upstream validation only, not human accessibility or legal claims.

No hosted stress traffic was sent. Public checks were low-volume health/readiness
and a null-input bundle smoke. At session start the live deployment reported
`91ddbb9580a7eccdf2d93736113e1fe8af6a9445` and accepted null violations (200 ZIP),
contrary to the stale earlier handoff's old-deployment warning.
