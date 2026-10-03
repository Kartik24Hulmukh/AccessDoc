# AccessDoc native hardening continuation — 2026-09-30

## Outcome and exact scope

Source candidate: `01c74db4613239c5c171a55fc7395be90c54751c` on `harden/accessdoc-v1-launch`. Continued from `78736f2ef9d10e4b37243a52be27b999e2c0c26e`; reused draft [PR 95](https://github.com/Kartik24Hulmukh/AccessDoc/pull/95). No merge or launch approval was performed. The report describes engineering evidence, not guaranteed traction, real-human evaluation, certification, or production capacity.

Frozen before-code failure receipts and environment-restored suite precede this turn's edits. First baseline had eight missing-browser failures; installing the missing Chromium restored the **unchanged** source to **906 passed, one deployed-test skip, 201 subtests**. That environment repair is not a product gain. Preserve all intermediate failed runs, including hosted failures, rather than presenting only green samples. Final-source local verifier: **all ten gates passed, 936 tests passed, one deployed-test skip and 207 subtests**. This is 30 additional passing tests versus the environment-restored baseline. Three warnings originate from intentional duplicate-ZIP hostile fixtures, not unhandled resource errors. Final-source local and hosted completion receipts live under `docs/evidence/native-hardening-2026-09-30/`; source and evidence-only successor commits are distinguished by attribution metadata.

## Artifact and integration decisions

Inventoried 14 supplied artifact entries, including duplicate uploads, catalog, prior patches, research archives and delivery receipts; recorded sizes, hashes and archive member bounds. The reattached delivery ZIP's 47 member hashes matched its supplied manifest. Inventoried branch heads rather than blindly merging historical branches or reapplying already-delivered patches. This continuation follows existing product decisions, not a new brainstorming exercise.

The `repos.md` catalog explicitly lists Microsoft Playwright and Deque axe-core. Reused their existing local integrations for actual browser revision/cancel/reset tests and accessibility/CSP checks. Their value is reproducible UX failure detection, not cosmetic demos. Added **aiohttp 3.14.3 + aiodns 3.6.1/c-ares** to close measured uncancellable DNS/header and connection-admission gaps; they are native transport dependencies, not falsely attributed catalog connectors. The installed dependency snapshot was audited with pip-audit 2.10.1, with no known advisories reported, and a CycloneDX SBOM retained.

Did not add generic RAG, memory, autonomous-browser, connector, or OCR repositories just because they were listed. The approved application turns supported scanner/manual evidence into deterministic report/receipt bundles. Arbitrary PDF/ZIP document ingestion and OCR are **not** established capabilities; rejection of corrupted PDF/ZIP inputs is boundary evidence, not OCR success. Adding such scope would require separate parsers, licensing/privacy review, deadline-owned workers and tests. No PDF/UA or legal-conformance claim is added.

## Five-point council premortem and disposition

Four read-only AI workstreams covered founder/product, principal architecture/SRE, adversarial review, and a second independent native-resource review. They are not 100 human evaluators or release signatories.

| Risk | Measured failure | Remediation and evidence | Remaining boundary |
|---|---|---|---|
| 1. Large evidence/output exhausts memory or rejects valid handoff | 500/1,000 findings yielded 422 because of a hidden 100 KiB receipt cap; 500-node receipt was already 115,061 bytes | Coherent aggregate `REPORT_MAX_BYTES`, typed 413 before eviction, startup failure if required storage is absent. Both 500 and 1,000 findings generated 201 and downloaded valid PDF/HTML/receipt in all three samples each. Input/tree/finding and process admission bounds remain enforced | Per-process quotas are not distributed tenant quotas; invocation CPU/memory caps and staging soak still required |
| 2. Async work deadlocks/leaks after winner/deadline | Four resolver-stalled losing threads survived deadlines and later issued four primary POSTs; missing usage reauthorized the same budget twice | Owned async selector loop, cancellable resolver await, process-wide I/O admission held to actual termination, shared prompt+completion ledger, pooled connections. Equivalent synthetic DNS await: four cancellations, zero late primary arrivals and zero hedge threads. Unknown usage retains authorization; overspend is not success | Synthetic DNS is not exhaustive real c-ares/OS/fork fault testing; provider billing still needs an independent server-side cap |
| 3. Parser/OCR or upstream timeout escapes request budget | 150 ms authorization took 614.35 ms serial / 400.46 ms hedged on slow response headers; 408 backoff left a sleeping loser | Header/body/DNS/native task deadlines; interruptible cancellation-event retry waits; clamped hedge readiness; cancellation completion reserve is inside the existing deadline. A real Windows active-call-at-return failure was reproduced locally with a controlled 30 ms delayed callback, then fixed without adding caller grace | No OCR pipeline is claimed. Native task/OS stalls beyond tested limits are not mathematically ruled out; CPU renderer hard limits remain operator requirements |
| 4. Gateway failure, spending or misleading readiness | Token budget ignored prompt/losers and unknown usage; require-auth deployments reported ready while POST returned 503 | Shared conservative ledger, 429/5xx fail-fast breakers, account-wide billing hold cancels speculative siblings. At the default configuration, at most two lanes may precede knowledge of billing exhaustion; no new dispatch after hold. Both adapters' readiness now fails closed for missing required auth. Hedge traces inherit the parent trace | UTF-8/framing authorization is not a provider billing guarantee. A sub-200 ms routing timer is not sub-200 ms model completion |
| 5. UX/private-data confusion destroys user trust | File/sample and guidance evidence could differ; failed replacement destroyed last good download; client/selector sent despite incomplete disclosure; idle TTL retained private payload past expiry | Revision snapshots include files; sample clears upload; guidance bound to last successful evidence; last labelled ZIP retained; native Cancel/New report and late-reply guards. Client/selector omitted from external prompt, help-text risk disclosed, selected coverage counts explicit. Shared monotonic expiry removes store references without traffic; reset clears page state | No secure erasure, provider deletion, browser-download deletion, tenant-bound storage, human consent, or legal approval is inferred |

## Validation and reproduced improvements

- Original 500/1,000-finding HTTP storage fixture: **six 422s -> six 201s**, with all 18 PDF/HTML/receipt downloads returning 200 and correct receipt counts. This is an acceptance/reliability improvement, **not a latency speedup**. Three-sample percentiles are descriptive maxima at P95/P99, not SLO proof.
- New scoped UI run: **12 passed, zero skips**, using the real loopback bundle endpoint and shipped ZIP verifier. Remediation, delayed replies, retry and file-read controls are explicitly synthetic; real provider UX was not certified.
- Native independent review initially found open-circuit 30 ms authorization taking 501 ms and 408 loser delaying a winning fallback until 2.005 s. Rechecks returned in roughly 2.4 ms and 34 ms with no hedge threads in those cases. Preserved initial findings and subsequent source-drift notes.
- Initial hosted evidence gate failed because it installed a hardcoded dependency list without aiohttp. It now installs the shared runtime/dev graph; a new workflow test guards that path. The Windows "one billing call before the unknown failure" expectation was replaced with the actual bounded speculative contract, plus a stronger known-hold cancellation regression—not a false claim that prior failure passed.
- A subsequent Windows run found one active native call at return despite the caller being under 200 ms. The deterministic delayed-completion test was frozen failing before changing the cancellation sub-budget from 10 ms to at most 50 ms/one-third remaining time. No arbitrary production sleep or added deadline grace was introduced. Final equivalent 150 ms slow-header measurements were **101.07 ms serial / 101.22 ms hedged**, with zero active native calls and zero hedge threads in those observations. Corrected idle-TTL harness (original assumed an expired object still existed): at age 2.2 seconds with a one-second TTL, zero backing bytes and no retained payload **before touching get/stats**; both missing-required-auth readiness responses were 503.
- Local 100-request / eight-worker valid bundle gate and nine malformed-input contracts passed; 1 -> 100 finding expansion is the precise "100x" denominator. **Not** 100x production traffic.
- Local 100 synthetic socket workflows, including 40 disconnects, passed: no observed unhandled thread exceptions, server errors or new threads after shutdown. Recovery probes were **2.35 ms health / 1.03 ms readiness** on the first candidate. Final source recovery rerun: **1.62 ms health / 0.99 ms readiness**, again no observed unhandled thread/server errors or new threads after shutdown. No human participation is claimed.
- Both adapters' ten-second authenticated 16-worker overload runs passed with deliberate 503 admission rejections, valid successful ZIPs, and successful recovery. API adapter: 288 successful bundles / 785 expected 503s; self-hosted: 317 / 825. Successful P99 about 259–260 ms: no claim every overloaded report finishes under 200 ms.
- In-process 200-bundle / 16-worker stress and ten subprocess cold starts passed with no cross-request evidence leakage observed. Hostile-input stress: **15 checks, zero failures**. These are bounded local exercises, not prolonged staging, real users, or public-endpoint stress.

### Preserved benchmark comparison (no speedup claim)

Same `hardening_load.py` workload: 100 requests, eight local render slots, one valid fixture, all 200 and identical bundle hashes. Earlier preserved receipt vs first native candidate `5c43b01` and final source `01c74db`; the latter was actually rerun rather than inferred from unchanged bundle code. Single short runs on a shared sandbox are not controlled capacity experiments. The measured latency/throughput change below is **worse**, not hidden or called a gain; repeated matched staging measurements are needed for attribution.

| Measure | Preserved previous receipt | First native candidate | Final source |
|---|---:|---:|---:|
| P50, ms | 47.30 | 65.60 | 77.50 |
| P95, ms | 66.60 | 88.00 | 106.50 |
| P99, ms | 71.20 | 105.90 | 128.90 |
| Throughput, requests/s | 163.33 | 120.70 | 103.26 |
| RAM floor, KiB | 35196.00 | 35284.00 | 35132.00 |
| RAM ceiling (max RSS), KiB | 45032.00 | 45180.00 | 45516.00 |

### Final native live-provider samples

The source candidate's final run used explicit managed egress rather than ambient proxy/netrc discovery. Three independent samples per requested model; no model removed or substituted, no widened model windows. Four twelve-call runs were performed as the native source changed, not retried until a failed gate happened to become green; all intermediate reports remain. Historical prior-turn Kimi 504/11-of-12 remains a historical failure, not overwritten. Each successful run is a bounded spot check, not provider uptime/throughput certification.

| Model | Successes | P50 ms | P95 ms | P99 ms |
|---|---:|---:|---:|---:|
| glm-5.3 | 3/3 | 6190.16 | 6745.66 | 6745.66 |
| glm-5.3-flash | 3/3 | 4120.69 | 4180.18 | 4180.18 |
| qwen3.8-27b | 3/3 | 10823.00 | 11009.57 | 11009.57 |
| kimi-k3 | 3/3 | 18805.89 | 19261.25 | 19261.25 |

Three synthetic resilience probes passed (429 failover, fail-fast outage, static fallback). Slow models still take seconds; these measurements do not satisfy a sub-200 ms provider-completion claim. Conservative token reservations and returned usage were checked; no independent provider invoice/billing certification was performed.

## Hosted source validation

All **13 observed hosted checks** on source `01c74db` succeeded: both push/PR Ubuntu runs (including required Playwright/axe, GSA OpenACR validation, Docker build/smoke), both macOS and Windows portability runs, dependency-security runs, lint, evidence, GitGuardian, and preview comments. Windows/macOS browser-related tests were skipped where the optional browser tooling was absent; the Linux browser/a11y gates actually ran. These successes repair, not erase, the earlier evidence and Windows failures. Local source/live statuses are success; exact-target and human approval statuses remain pending. The evidence-only successor requires its own observed CI, not an inferred pass.

## Stop-ship gates and required operator/human work

The exact source preview probed earlier returned **302 to Vercel SSO**, with **zero functional checks** and no observed deployed SHA. The Git token and model key are not Vercel deployment authorization. No protection bypass, public-upload promotion, or invented human signature was performed. GitHub Actions secret metadata contained zero secrets; that says nothing about private Vercel project settings.

1. Rotate credentials already disclosed in chat. Install replacements through the approved secret manager, not git or chat. Configure explicit egress if required, provider-side spending caps, and approved optional-model processing.
2. Supply authorized Vercel automation access/bypass and final chosen deployment origin. Set pilot API auth, provider/WAF quotas, replica/memory/CPU/invocation limits, approved OTLP collector/log retention, and rollback configuration. Run exact-SHA protected-preview smoke and staging load/alert/rollback drills on the **final** candidate, not an old alias or local substitute.
3. Complete the existing practitioner protocol and independent accessibility/security review, including the user's requested real-person evaluation. Provide named release/security/copyright owners and legal/name/privacy/public-copy approvals. AI council and synthetic users cannot supply those signatures or demonstrate traction.
4. Keep PR draft and auto-merge off until hosted checks, exact-target evidence and human release gates pass. Per-process shared pilot auth/capability URLs are not a production multi-tenant identity/storage/billing system.

For reproducibility install `requirements-dev.txt`, install local Playwright Chromium and pinned axe-core, run `scripts/verify_release.py`, then the recorded local load/chaos/native ownership commands. The evidence manifest binds raw reports and scripts by SHA-256. Generated claims remain experimental-beta claims under existing release policy until the remaining gates pass.

Evidence-only lint correction: the captured historical branch inventory and raw GitHub job logs are immutable evidence, not active version declarations or source-encoding files. Version lint misclassified old branch names, and the BOM gate correctly caught UTF-8 BOM bytes in raw downloaded logs. Unaltered captures are now in `immutable-historical-captures.zip` with a per-member hash manifest, rather than falsifying historical versions, stripping raw bytes, or weakening any source lint check. Both hosted lint failures and intermediate local reclassification failure are preserved inside that archive.

Final portability refinement: one evidence-only successor's Windows job reported WinError 10053 on the **malicious client** while it continued dripping into a rejected unread body. The regression now accepts reset/abort only with the exact server deadline/oversize decision correlated to that same peer, while preserving deadline, permit-recovery, zero-server-error and teardown gates. Quiet timed-out clients still must receive an actual HTTP 408; a negative uncorrelated-reset control must fail. Five focused tests and eight subtests passed locally. Production application/gateway code is unchanged; this is not a claim that the failed Windows job passed. Updated full-suite and hosted receipts are supplied in the delivery archive.
