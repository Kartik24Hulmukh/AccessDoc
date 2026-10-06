# Parallel hardening continuation — 6 October 2026

## Verdict
HOLD. No merge, deployment, paid provider calls or human approval occurred. PR95 remains the existing release PR on harden/accessdoc-v1-launch. This continuation closes specific source defects; it does not certify public launch, customer demand, arbitrary-document OCR, fleet capacity or hard-real-time operation.

Validated local source commit: `10aeb3eef1b423985533bf1b27500166e6827abb`. The following evidence-only commit adds receipts, not runtime/test changes. Native diagnostic guards continue authenticating exact committed source bytes; no normalization or acceptance weakening was added.

## Frozen baseline and preserved failures
- Unchanged base0cce6ae: 1220 passed, one failed,23 skipped,436 subtests,69.66s. Failure: test_global_reserve_drains_late_final_batch_retirement did not necessarily produce a failed native task when work expired between two successful batches.
- Live base checks: both Linux test jobs and both macOS full-suite steps passed. PR macOS run37478447257 failed the later hardening_load stage, while push37478440389 passed. Existing public annotations identify only exit1; private load artifact was not obtained. The former handoff therefore did not establish all-green release status.
- First committed candidatebed1fda: all nine non-test hygiene gates passed; tests1259passed/2failed/1skipped/510subtests,108.85s. Both failures were an omitted refresh of the changed cleanup-test byte digest. Preserved release-verifier.json; corrected exact hash in10aeb3e, without weakening the source guard. A preceding dirty-tree guard run also failed as expected because committed source still contained old exporter bytes.
- An attempted final verifier command from the wrong directory exited2 before running tests; no validation inferred. Correct final invocation is recorded below.

## Implemented source and tests
1. OTLP daemon no longer treats a50ms finalize poll expiry as permission to dispose. It retains existing ownership until the shutdown caller signals finalization, preserving caller budgets and useful final work. Real loopback/barrier regression failed on old source and passed after the minimal change.
2. Corrected the late-retirement fixture: two fast useful requests, then a held third real request with delayed failed-task retirement. Original timing/resource assertions retained; separate between-successful-batches cutoff regression added. This proves native retirement of a failed task, not independently that the task.cancelled flag was true.
3. Darwin RSS now obtains resident_size_max and resident_size from one Mach task_info snapshot instead of comparing an earlier getrusage peak with later current RSS. ABI and fallback unit tests added. This removes a demonstrated sampling race; it is NOT a proven reconstruction of the prior hosted load failure. Native Darwin acceptance still requires hosted checks.
4. Invalid explicit ACCESSDOC_REQUIRE_AUTH values fail closed with503/AUTH_CONFIG_INVALID, including empty values and even matching credentials. Missing configuration retains documented local compatibility. Real sockets test both adapters, readiness and non-reflection.
5. Local zero-spend launcher strips inherited global/traces/metrics/logs OTLP endpoints and headers, plus existing provider/legacy keys. This is not an OS network firewall or fleet spend cap.
6. Portability CI now publishes bounded credential-filtered load-failure labels and allowlisted memory counters only after the load step fails. Original failing command, thresholds and gate verdict remain unchanged.
7. Exact native source/test diagnostic hashes refreshed. No test skips, timer threshold increases, retry-until-green or test-removal was introduced.

## Final measured validation
- All10 local release verifier gates PASS. ResourceWarning-as-error full suite:1261passed,510subtests,one genuine deployed-target skip,three intentional duplicate-ZIP warnings,110.93s. Optional real browser prerequisites were actually installed;22 earlier dependency skips disappeared, not hidden by mocks.
- Real Chromium/axe output self-audit:zero violations across report and VPAT at1280px and320px. Browser/sample/auth/scan-handoff/reflow focused run17PASS. These do not replace qualified assistive-technology review.
- Independent AI engineering reviews covered lifecycle, telemetry ABI and diagnostic/verdict preservation. Scoped20native,45security/74subtests,24telemetry/reporting and12corrected source-guard tests passed; overlapping counts are not added to full-suite totals. AI reviewers are not genuine human participants or release signatories.
- Source/version/BOM/config lints and diff whitespace checks passed. Docker is not installed in this environment: no local image build/scan/rollback or GHCR publication claimed.

## Same loopback workload, baseline versus candidate
8workers,100requests,unchanged hardening_load workload;100/100valid deterministic bundles in both runs. Candidate workload receipts were taken during the coordinated source handoff, before final guard-only corrections; no throughput-related runtime code changed afterwards. They are local descriptive samples, not controlled causal performance gains. Candidate is slower in this sample; no speedup claimed.

| Metric | Baseline | Candidate sample |
|---|---:|---:|
| P50 ms | 63.6 | 82.9 |
| P95 ms | 87.5 | 121.4 |
| P99 ms | 97.5 | 126.7 |
| Throughput requests/s | 120.26 | 92.45 |
| RSS floor KiB | 34780 | 34676 |
| RSS peak KiB | 68108 | 68100 |
| RSS after KiB | 66016 | 65948 |

## Additional bounded synthetic torture
-100workers/200mixed requests:134valid200,33oversize413,33corrupt422;zero unexpected5xx,contract violations,transport errors,admission retries or transport retry errors. P50/P95/P99:6509.23/11530.81/12788.95ms. Throughput:11.92rps. RSS floor/peak/after:52.0/219.7/137.3MiB. Health/readiness/fresh bundle recovery200 at{'/healthz': 1.32, '/readyz': 0.95, '/api/bundle': 7.75}ms. Three recovery samples below200ms are not a universal bound or100x capacity proof.
-100synthetic socket workflows,40disconnects:zero observed unhandled thread exceptions,server errors or remaining new threads;real body interruption rejection checked. Health/readiness200 at1.72/1.18ms. No human personas claimed.
- Authenticated15s/8worker soak on both adapters: useful bundle rate36.01/36.48per second, controlled503 overload and successful fresh recovery. One short local soak is not sustained staging acceptance.
- Offline429failover,503fail-fast and static fallback PASS;outage decision0.1ms. No live Melious samples, model entitlement or provider SLA proved; exposed chat keys were not reused.

## Five-point premortem disposition
| Risk | Remediation/evidence | Still required |
|---|---|---|
| Large-file memory exhaustion | Existing strict supported-input limits and malformed/oversize gates retained;paired RSS counters;local burst receipts | Actual fleet/edge/container bounds, sustained target soak, hard resource termination |
| Async deadlock/orphan cleanup | Native ownership/finalize fix and failed-task retirement/cutoff regressions;ResourceWarning gate | Exact all-OS hosted checks;remaining private Event/Future/registry mutex deadline limits |
| OCR/parsing/gateway timeout | Supported axe/manual boundaries fail closed;native deadline and offline429/503tests | OCR is outside this product boundary;live provider availability/budget/latency not established |
| Misleading evidence/readiness | Source hashes,real-browser checks,source-faithful existing exports and distinct receipt scopes | Genuine practitioner/AT/security/legal decisions;checksums do not authenticate scan truth/compliance |
| Unsafe hosting/no demand | Strict auth config and egress-safe local launcher;no speculative hosting or dependency purchase | Protected exact target,collector/alerts/retention/spend/rollback,owner decisions and actual demand |

## repos.md decision and artifact reconciliation
Four agents reviewed supplied reports,plan,pasted handoff,all of repos.md and all four ZIP inventories/content pertinent to this converter. ZIP CRC/path/symlink checks passed;no unsafe extraction or attachment execution. Retain existing aiohttp/c-ares,ReportLab/OpenACR,Playwright/axe,OTLP and verifier. No new framework/plugin integration is justified by these defects;existing native primitives and QA tools solve them. Reject speculative OCR/RAG/vector/orchestrator expansion,blind catalogue installs,stale malformed patches and conflicting bundle/WCAG specifications. Existing upstream GSA CI validator remains;its default-branch pinning is a reproducibility follow-on. No Axiom-Grid repository was changed.

## Outstanding launch verification — cannot be fabricated
- Final exact-head required GitHub checks must complete green. Earlier failures remain evidence,not erased by a later success.
- Issue96:eligible commercial/no-charge target, fresh private auth/platform credentials,exact-source smoke,actual limits/spend/collector/alert/retention controls,sustained soak and authorized immutable rollback rehearsal. GHCR is an image registry,not an application host.
- Issue97:ten actual consenting practitioners and qualified independent accessibility review;no recruitment/trial completion inferred from synthetic workloads.
- Issue98:actual named security/legal/release-owner assent scoped to final source and deployment. Repository access/AI checkboxes do not substitute.
- Vercel email sign-in reached authenticator verification,which returned Invalid token on one approved private submission. No code was reused,recovery started,protection disabled,billing changed or production promoted. A fresh successful sign-in is still needed for operator inspection.
- Native review separately demonstrated hidden Event/Future internal-mutex acquisition and publication can exceed requested budgets under controlled private-lock holds;registry/snapshot owner locks have further limits. No universal hard-real-time deadline or zero-coroutine-leak guarantee follows from finite tests. These are follow-on design risks,not the proved cause of hosted hardening_load failure.

## Reproduce
UsePython3.13 and requirements-dev.txt;install real Playwright Chromium,websocket-client and axe-core4.11.0 for browser gates. Environment snapshot is included. Run:
```bash
python scripts/verify_release.py
python scripts/hardening_load.py --output load.json
python scripts/concurrent_bench.py .
python scripts/disconnect_chaos.py --output disconnect.json
python scripts/hosted_soak.py --seconds 15 --workers 8 --output soak.json
python scripts/gateway_bench.py --probes-only --output gateway-probes.json
python scripts/self_audit.py
```
These commands are loopback/offline except explicit browser dependency installation. Do not substitute a public origin or provision provider secrets to source CI. Final production verdict remains HOLD until real remaining evidence exists.
