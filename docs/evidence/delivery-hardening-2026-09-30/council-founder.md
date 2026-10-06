# AccessDoc — founder release council

**Decision: HOLD public launch/public uploads. Continue source-only, supervised local practitioner evaluation.** This is an AI-assisted product/founder review, not a convened human council or independent approval. No repository edits, deployments, credential-file access, new research, or test reruns were performed.

Reviewed source: `4270da84dc8f89a99b2e354a62c92543fe639edb` (clean working tree). Status is based on existing receipts, not refreshed cloud results.

## Product and evidence boundary

AccessDoc converts structured accessibility scan evidence (axe JSON, optionally recorded manual findings) into a reviewable, tamper-evident evidence bundle: HTML/PDF, receipt, OpenACR mapping, manifest and attestation, with optional SARIF, VPAT draft and EAA exports. The supervised Playwright/axe handoff demonstrates an authorized page → bundle → integrity verifier. It is **not an OCR/document-remediation pipeline**, whole-site audit, certification, or proof the source scan was truthful. HTML is the accessible primary artifact; PDF is untagged. Local attestations are unsigned unless the signing workflow is used. AI remediation is optional advisory guidance.

Sources: `AccessDoc/README.md`, `examples/agency-handoff/README.md`, `tests/test_scan_handoff.py`.

Latest strict local verifier: **900 passed, 1 skipped**, 178 subtests; all listed local gates PASS. This supersedes the earlier file named `final-suite.log`, which recorded two failures. The remaining production journey needs `ACCESSDOC_PRODUCTION_URL`. Saved hosted CI still had test jobs running; combined status was failure, live-gateway failure and exact-target smoke pending. Live Kimi succeeded 2/3, with one 504 at ~40 seconds. Preview 401 was reported; the saved smoke failed readiness and observed no commit. Neither deployment creation nor Vercel status success proves application acceptance.

Receipts: `/data/accessdoc-turn4-strict-final-verifier.json`, `accessdoc-turn4-final-ci-progress.json`, `accessdoc-turn4-final-live-gateway.json`, `accessdoc-turn4-protected-target-smoke.json`; production skip in `tests/test_e2e_journeys.py`.

## Three highest-impact next steps

### 1. Establish an exact-artifact release receipt before hosted use

**Owner: engineering/release operator.** Wait for completed hosted CI on the full SHA; retain clean-install tests, security/SBOM and artifact receipts. Use an approved protected-preview access mechanism, without disabling protection, to run the shipped `scripts/production_smoke.py`. Require matching full SHA before and after smoke, valid bundle/CLI verification, and all seven negative contracts. A 401 is an access barrier, not evidence of a broken renderer or a passing smoke.

Kimi's live gate remains red. Preserve failed samples; resolve and rerun within the existing budget, or have the release owner explicitly approve a narrower deterministic-core preview with AI unavailable/unpromoted. Do not silently waive the four-model gate or enlarge timeouts just to pass. For an eventual hosted pilot, enable auth and provider-wide limits/spend alerts, verify logging/retention, and rehearse rollback in **under five minutes**. Metrics: completed green required checks; zero SHA mismatches; all smoke contracts pass; live successes/timeouts and degraded responses reported separately. Three samples cannot establish a tail-latency SLO.

### 2. Validate an accepted handoff with actual people, not synthetic traffic

**Owner: founder/product, with an independent accessibility practitioner.** Run the existing ten-session protocol: five practitioners and five agency report owners. Use synthetic input for the controlled exercise, but actual human participants. Preserve existing thresholds: **8/10 unassisted completion; median corrections ≤2; zero certification misinterpretations; 4/10 request a second real, non-sensitive export.** Obtain independent review of generated output.

Then observe consented real-engagement handoffs: correction/editing minutes, recipient acceptance/action, and completed second use—not merely stated intent. Record manual/assistive-technology coverage and untested states; deliver HTML first. The existing 100 loopback workflows, including 40 disconnects, test mechanics only: **not 100 humans, customers, paid engagements, traction, or 100× capacity**. Do not build billing, OCR or a broader platform before this evidence.

### 3. Close named approval and misleading-copy gaps

**Owner: founder/release owner, qualified legal and accessibility reviewers.** Record the name/ownership decision, copyright owner, security contact and independent approvals against the candidate SHA. Existing naming research reports a collision; it is not clearance. Do not repeat that research or infer geographic permission from it.

Before publication, reconcile README contradictions about missing-key 200/offline versus 503, and serverless availability. Remove stale readiness percentages from launch-facing material. Preserve explicit limits: integrity ≠ authenticity/conformance; VPAT is a draft; PDF is untagged; audit date is caller-supplied; privacy/retention claims need deployment evidence. Metrics: all three `RELEASE_GATES.md` tracks have named sign-off, and no conflicting operational or prohibited certification/production claims remain.

## Ship boundary

`docs/RELEASE_PROCESS.md` allows source-only practitioner preview, not automated publishing. Proceed with local supervised evaluation now. **Do not publicly launch, operate public uploads, auto-merge, or promise 100× traction.** A hosted pilot is only a later, operator-approved bounded step; public release requires repository, practitioner, and editorial/legal gates independently satisfied.
