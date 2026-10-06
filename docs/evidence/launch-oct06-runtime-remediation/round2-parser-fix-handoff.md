# Parser rejection trust fix — owned API source frozen again

Reviewer blocker confirmed, not waived. On runtime-bypassed keepalive, command/path may already be assigned when header parsing rejects; old headers survived and propagated the preceding request's traceparent. The prior first-freeze lifecycle success did not cover this partial-parse case.

## Original run protected

Before source edits, `/data/accessdoc-evidence/round2-release-verifier.json` had all ten PASS entries and no full-verifier/test process remained. Its SHA256 before and after this patch is `b209691c20ed4be0b9c2d3076265b3c2fe574a068788e8ddd5ef055956259838`. Original4c8ab31 full-suite receipt was not overwritten or rerun; it is old-source evidence, not acceptance of this change.

## Causal receipts (all retained separately)

- Supplied reviewer probe/results/log were read and left unchanged.
- `round2-parser-reviewer-before-results.json` + `.log`: same reviewer probe with output path redirected; RuntimeInline and RuntimeDelegated reused stale parent, stdlib minted a clean root. Two spans/completions each.
- New `tests/test_vercel_parser_rejection_lifecycle.py` before source fix: `round2-parser-newtest-before.txt`, two test methods with **six failing subcases**: both runtime shapes failed header-count431, header-line431, and overlong-request414 stale-header checks. Other parser cases and parsed501 remained passing. No weakened expectations.
- `round2-parser-reviewer-after-results.json` + `.log`: same reviewer probe, now all three dispatch styles have no stale-parent reuse and exactly two spans/completions. Outputs do not reflect private parser canary.
- `round2-parser-final-focused.txt`: **59 tests passed in21.785s**, ResourceWarning-as-error, existing venv, -B, clean synthetic environment. Includes new partial-parser module, existing dedicated runtime lifecycle module, auth configuration, hosted boundary/metrics/UI/surface/admission/lifecycle and stdlib error contracts. Counts overlap previous57; do not add them.

## Narrow source change

In serverless `send_error`, parser-rejection codes **400/414/431/505** invalidate untrusted/prior headers and cached/thread trace before constructing the rejection response/root trace. Fully parsed unsupported **501** keeps the current request's valid inbound parent. Authentication/body error methods were not changed; limits/thresholds were not changed. Existing reentrant request owner still handles exact-once count/log/SERVER span and teardown; HEAD nesting remains unchanged.

New loopback tests cover repeated-request partial header count/line rejection, malformed request400, unsupported HTTP version505, overlong request414, and separately parsed unsupported501 using a different current inbound parent. Assertions retain unique request IDs/spans, root traces for parser rejections, accepted current501 parent, private finite routes/no canary reflection, exact two request counters/logs/spans and cleared cached/thread context/owner at both completions. Two runtime bypass dispatch forms plus stdlib are exercised.

## Frozen hashes (supersede prior handler hash)

- api/handler.py: `6a989175e13c82f23cd15502134a3671a7b36bfa16870e7a682f6438d50fbbe0`
- tests/test_vercel_runtime_lifecycle.py: `7c6324e7238ad756a2330791bbb95df2fc9ebfecfb5da115fad1f381e4ec702e`
- tests/test_vercel_parser_rejection_lifecycle.py: `980289f38ba44f9a5f9d484e54c3eb71a276e0f360ddebb18d3a6d23889e561d`

Owned source frozen again; no further edits unless requested. `git diff --check -- api/handler.py` passed. No commit/stage/push, Docker/hosting changes, provider traffic, secret retrieval/use or deployment/human acceptance. Lead owns combined commit, fresh full-suite/exact-head CI and protected target acceptance. Earlier default-interpreter import failure and original live preview500 remain distinct preserved evidence; neither is explained away by this fix.
