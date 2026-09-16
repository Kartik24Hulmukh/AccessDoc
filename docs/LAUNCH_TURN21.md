# AccessDoc — Turn 21 launch checkpoint (2026-09-16)

## Decision
Controlled beta candidate only; broad hosted launch remains blocked. No traction multiplier is established.

## Attached-file audit and frozen baseline
Both supplied Turn 19/20 reports read in full. Base main 1d0ec58f37b941ed428088656c27d634bb31169c; PR 65 was open with successful checks. Reports are historical claims, not substitutes for fresh testing.

Baseline: 10/10 release checks; 760 tests, 12 skipped; stress 15/15. Fresh local 100-worker / 200-request mixed JSON benchmark: 134 HTTP 200, 33 HTTP 413, 33 HTTP 422; zero unexpected 5xx, contract violations or transport errors. P50/P95/P99 11169.10/20707.45/21952.10 ms; throughput 6.8 rps; RSS floor/peak/after 43.7/321.7/210.5 MiB. Baseline ran alongside tests, so comparisons to Turn 20 are confounded by shared CPU. Turn 20 values: 7649.8/18058.0/18921.2 ms, 8.34 rps, RSS 42.1/304.1/189.5 MiB. These are observations, not regression attribution or a production capacity proof. Retained RSS does not prove absence of a leak. No measured traffic baseline establishes a 100-times production multiplier.

## Actual remediation
A real file-only practitioner workflow was broken: native required textarea validation stopped submission even when a JSON file was selected (zero API requests, no result). Change the textarea requirement when file selection changes; clearing the file restores required paste input. Rebuild embedded serverless assets. Add Chromium regression coverage for valid file-only download and ZIP verification, clear selection, corrupt upload, oversize file and recovery. Source fix took two validation cycles: first exposed embedded-asset drift; second passed after regeneration.

New local-only `scripts/browser_journeys.py` exercises 20 viewport/locale profiles across six workflows. This is synthetic browser coverage, not human participant research. Its first run had 19 instrumentation failures because CSP correctly rejected string evaluation; instrumentation was changed to locator assertions without weakening CSP. Final results are recorded in the follow-up evidence section.

## Verification
After installing real browser prerequisites: release gate 10/10 PASS, 761 tests in 60.868 seconds, no skips, including opt-in live deployment health. Two targeted hosted UI tests passed. Live production malformed JSON 400/61.7 ms; valid bundle 200/72.5 ms; remediation 200/71.8 ms with explicit offline-kb degradation; gateway configured false. Twelve truncated/RST local uploads followed by health 200/7.4 ms and ready 200/2.0 ms.

Direct upstream probes: four canonical model identifiers returned HTTP 200 and nonempty answers with 128-token caps, latencies 684.2/879.8/740.0/1504.9 ms in chain order. An initial eight-token cap exhausted reasoning and produced empty content; HTTP 200 alone is not a valid model-answer success gate. Provider failures were not induced on shared production. Local deterministic fault tests cover 429/5xx breaker and routing overhead; sub-200 ms means routing decision overhead, not complete network response.

## Five-point premortem (single-agent review through four roles, not a real swarm)
1. SRE: memory exhaustion from large input — bounded JSON rejection passed; sustained isolated RSS soak and fleet limits still required.
2. Architect: stuck workers/disconnects — 200-request burst and 12 socket abort recovery passed; not proof of zero deadlocks at all scales.
3. Human evaluator: accepted-input UX blocks completion — file-only defect reproduced and fixed. OCR/PDF/Office ingestion is unsupported scope, not tested as working.
4. Red team: provider cascades/spend — local breaker tests pass; hosted credential, WAF quotas, spend kill switch and collector verification remain operator gates.
5. Founder: evidence overclaim/adoption failure — 761 tests do not imply market traction or legal accessibility approval. Recruit practitioners and measure verified first-bundle completion, time to reviewed handoff and repeat use.

## Catalog integration audit
Fetched frontier-oss-ideas/docs/LEVERAGE_REPOS.md, the catalog referenced by Turn 20. No literal repos.md was attached. Catalog is for an adjacent product: study thin adapters, native fetch lifecycle and test discipline; do not import its unrelated Next.js/vector/search stack. Existing Playwright/axe tooling was enabled rather than adding production dependencies. No claim that the catalog lists OpenTelemetry or that every catalog item is integrated.

## Launch blockers and next checks
Rotate the two credentials exposed in task history. Configure a rotated Melious credential using deployment-platform access; verify hosted non-fallback answer on exact merged SHA. Establish WAF quotas, cost kill switch, collector receipt, staging sustained load and independent accessibility/security/legal sign-off. No Vercel credentials were supplied. Keep branch protection; merge only with all required checks green on current head. Rollback UI regression through revert of the fix commit and regeneration of assets, then rerun browser gates.

## Final browser-matrix evidence
120/120 checks PASS across 20 locale/viewport profiles; no CSP relaxation. Synthetic checks only.
