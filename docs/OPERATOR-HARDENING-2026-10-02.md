# Operator, telemetry and source-candidate hardening

## Scope and decision

Continued from `b7f97df3b3566768322d5e39b6ee2ada20e76189` on
`harden/accessdoc-v1-launch`. This is an engineering increment, not public-launch
approval. PR 95 must remain draft. Production promotion, exact-target smoke,
staging resource/spend/collector/alert/rollback evidence, and genuine human
security/accessibility/legal/release assent remain separate gates.

The newly connected GitHub integration authenticated repository owner
`Kartik24Hulmukh`. It does not authorize Vercel. The newly authorized supported
`client_secret_basic` client-credentials exchange returned HTTP 400
`invalid_client`, with no access token. Prior client-secret-post failure is
preserved in the preceding report. No Vercel protection was disabled, project
settings mutated, account access fabricated or human signature supplied.

## Council and implementation ledger

Parallel AI SRE/red-team and release/founder reviews are scoped engineering
reviews, not human evaluators or signatories. Their frozen reproductions precede
edits and remain in the capture archive.

- Independent generation/remediation admission switches in both adapters.
  Authentication remains first; disabled work returns 503 before body reads,
  capacity admission, rendering or provider work. Invalid configuration fails
  closed without publishing raw values. Remediation can be disabled while the
  deterministic bundle service remains ready. Generation disable blocks
  readiness, not liveness. GET/HEAD readiness agree.
- Hosted request lifecycle owns one completion log, request count and SERVER
  span per actual request. Correlation headers now cover direct ZIPs, HEAD,
  OPTIONS and errors. Arbitrary client paths/query strings, capability tokens
  and client addresses are omitted from completion labels. Header duplicates
  and keep-alive context reset have real-server regressions.
- Self-hosted parsed inbound trace is adopted before native serial/hedged work,
  fixing an independently reproduced upstream/completion trace split. Four
  independent after-cases retained the inbound trace across actual loopback
  upstream headers, gateway logs and HTTP completion. The shipped regression
  additionally requires the matching SERVER span and zero active native calls.
- OTLP reuses existing native owned transport instead of inactivity-only reads.
  A single sender owns drain/network/accounting, with shared absolute
  export/flush/shutdown budgets and bounded JSON acknowledgements. Partial
  rejection is failure, not retried or counted as accepted delivery. Native
  admission is shared with gateway traffic; this interaction still needs
  approved staging measurement. An empty later flush does not recover old
  losses. Expired cleanup remains owned and scheduled, not detached success.
- Source packaging reads clean committed HEAD blobs only, never untracked or
  ignored filesystem files. It rejects dirty/hidden index state, unsafe paths,
  symlinks and gitlinks, and emits full commit/tree provenance. Prior synthetic
  ignored/untracked/external-symlink canaries entered the old archive; after
  packaging excludes them and preserves public examples. Provenance is
  unsigned and is not secret-free, review or legal certification.
- Candidate workflow now installs required browser/system and pinned axe
  dependencies before strict verification. Windows executable-mode fixture
  uses explicit Git index mode even with `core.filemode=false`, preserving the
  original assertion rather than skipping it.

`repos.md` was rechecked against its prior digest. Existing catalog Playwright
and axe-core remain the selected real browser/accessibility handoff integration.
Exporter reuse and clean Git packaging use existing native dependencies and
standard library/Git, not invented catalog integrations. No generic OCR/RAG or
agent framework was added without a functional gap. The product imports
accessibility evidence; PDF/ZIP rejection is not OCR success.

## Frozen failures and remeasurement

A 100 ms OTLP budget against the same trickling collector took 645.90 and
645.68 ms before, with misleading successful flush. After took 67.88 and
67.75 ms, returned failed flush and counted one unconfirmed failed span, with
zero inflight spans. These are two local samples, not percentile/SLO estimates.
HTTP 200 partial rejection now separates accepted/rejected counts and returns
failure without collector text in public status. Default native cancellation
reserve is inside the deadline, so failure can precede full budget expiry.

Original actual operator fixture showed absent disable controls: both bundle
requests were accepted despite the proposed disable environment setting. This
was a missing requested capability, not a broken documented prior flag. Hosted
ZIP lacked correlation; hosted missing-auth HEAD readiness was 200 while GET
was 503; self-hosted HEAD was unsupported (501). The retained after fixture and
real-server tests exercise disabled admission and matching readiness status.

The first expanded full run had 997 passing tests, one failing direct-writer
request-counter test, one deployed-target skip, and 278 passing subtests. The
old mock bypassed the new completion owner. Replaced it with an actual valid ZIP
request requiring exactly one request and report count, not a weakened count.
Initial focused test-fixture failures and every full-run failure are retained.

## Bounded local load, not launch capacity

One eight-worker / 100-request loopback run returned 100 valid HTTP 200 bundles
with one deterministic digest. Reported P50/P95/P99: 99.0/134.0/146.9 ms;
throughput 79.73 requests/s; observed idle/peak/post-load RSS
34,568/66,844/64,672 KiB. Historical native-source run reported
77.5/106.5/128.9 ms, 103.26 requests/s and 35,132/45,516 KiB idle/peak.
These short shared-sandbox runs are not controlled attribution or enforced RAM
ceilings. Performance and observed peak memory are worse; no gain is claimed.
New hosted completion/exporter initialization is exercised, not cost-free.

100 synthetic socket workflows (40 disconnects) and the authenticated paired
five-second/eight-worker overload exercise passed locally. Soak hosted:
132 valid bundles/132 deliberate 503s, successful P99 249.53 ms; self-hosted:
148 valid/132 deliberate 503s, successful P99 247.57 ms. Both recovered to HTTP
200, with zero recorded invalid/transport errors. Not every successful overloaded
request is below 200 ms. These are neither 100 actual people nor 100-fold
production traffic, global coroutine-leak proof or sustained staging evidence.
No fresh paid provider test was run for this increment. Historical four-model
spot checks are historical, not exact-current-source/provider certification.

## Five-point premortem disposition

1. Memory exhaustion: clean-source boundary, response/queue/payload/input bounds
   and new admission switches; fleet CPU/memory/replica limits still operator gates.
2. Deadlocks/cleanup: serialized exporter ownership and deadline-owned native
   work; local saturation/cancellation/zero-budget tests, not universal OS proof.
3. Parser/OCR/timeouts: existing supported parser contracts retained; collector
   trickle bypass repaired; no general OCR feature promised.
4. Cascades/spend: independent new-work controls and honest partial rejection;
   shared native admission documented; no account spend cap inferred.
5. False readiness/release/traction: HEAD parity, exact Git provenance and real
   completion accounting; draft preserved. Source CI is not deployed smoke,
   AI council is not human assent, and no adoption is fabricated.

## Evidence and reproducibility

`docs/evidence/operator-hardening-2026-10-02/` retains frozen before/after
reproductions, scoped AI reviews, local load and failed-run captures with member
SHA-256 digests. The immutable capture archive is delivered in a base64 text
envelope (`immutable-local-captures.zip.b64`); decode it and validate the archive
and each member against `CAPTURE-MANIFEST.json`. Full local verification is recorded in `LOCAL-VERIFICATION.json`: all ten
gates passed; 1,000 tests and 282 subtests passed, with one deployed-target skip
and three intentional duplicate-ZIP warnings. Baseline was 946 passing tests
and 218 subtests. This does not establish deployed verification. Build actual source candidates only after the branch is clean and
committed; synthetic fixture provenance must not be called release provenance.

Install `requirements-dev.txt`, Playwright Chromium and axe-core 4.11.0; run
`scripts/verify_release.py`, new operational/lifecycle/native-trace regressions,
`scripts/hardening_load.py`, `scripts/disconnect_chaos.py`, and the loopback-only
`scripts/hosted_soak.py`. Validate the actual source archive against every
manifest member and full SHA/tree before using it.

No merge, public release, staging mutation, paid stress, human outreach,
participant booking or reviewer approval follows from this code increment.
Credentials disclosed in conversation require rotation through approved secret
managers. Valid project-scoped Vercel authorization plus actual participant and
reviewer identities/availability remain necessary to perform the blocked work.
