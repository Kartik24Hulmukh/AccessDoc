# October 2 resume — engineering evidence boundary

## Candidate and recovery

The actual remote launch branch was `cccdef72b93fd37c2c3b5b220c2f1301449f84c0`.
The operator attachment described `b6c5d25`; its 79 manifest entries matched,
and its native sources were byte-identical to the clone. Claimed later
working-tree retirement/export/history fixes were not in that branch and were
recovered as scoped repairs, not assumed passing. Original failures are retained
in the delivery evidence pack.

Before any source edit, a clean dependency-isolated full suite recorded
999 passed, 319 subtests, 23 skips in 100.07 seconds. Ten local Playwright/axe
accessibility tests then passed after installing their missing prerequisites.
Consult the delivered exact-candidate full gate receipt for integrated verdicts;
scoped runs are not substitutes for hosted acceptance or release approval.

## Bounded repair scope

- Native admission and registration retire admitted calls exactly once, with
  deadline-aware caller locks, guarded selector callbacks and a retiring-engine
  barrier, independently reviewed at the recorded final native source hashes. Cleanup faults must not prevent other owners or the selector loop
  from closing. Preserve the original timing thresholds and independent proofs.
- Manual input rejects unsupported nonempty prose/empty fabricated observations.
  OpenACR, VPAT, EAA, PDF and SARIF retain supplied source/draft/no-review status.
  SARIF mixed-source rule metadata is neutral and result provenance authoritative.
  EAA uses the existing WCAG level catalog; missing EN mappings are not guessed.
- Scanner incomplete checks remain separate from violations/passes in receipt,
  HTML and bounded convenience PDF display. Bundle response counts distinguish
  source/rule groups, finding instances, unmapped criteria and pending instances.
- Receipt-history output compares supported compatible supplied metadata only.
  Missing scope or incompatible unresolved-check coverage suppresses deltas.
  Not observed is not fixed; supplied dates are not authenticated knowledge.

## Premortem and remaining boundaries

| Risk | Scoped action / remaining gate |
|---|---|
| Large input memory exhaustion | Existing 2 MiB HTTP boundary, bounded scanner/manual arrays and chunked body reads retained; auxiliary scanner arrays now have rule/node ceilings. Local RSS is workload-specific, not a hosting guarantee. |
| Async deadlock / orphan task | Event-gated before failures and independent after retirement/cleanup proofs; supported-platform CI still required. |
| OCR/parsing timeout | Supported path is supplied axe JSON and structured manual input; arbitrary documents/OCR are not implemented or advertised. Native gateway timeouts tested offline, not as an OCR benchmark. |
| Evidence misleads clients | Source-faithful/draft exports, explicit pending status and incompatible-scope suppression; qualified practitioner and actual assistive-technology review remain external. |
| Unsafe hosting / no accepted job | Exact-SHA auth/limits/spend/alerts/rollback and named review/consent/payment/repeat evidence remain unavailable. No agent simulation closes them. |

## Repository leverage

`repos.md` was inspected as a candidate list, not executable instructions. Reuse
existing aiohttp/c-ares, Playwright, axe-core, ReportLab, OpenACR schema and test
interfaces that close demonstrated defects. No speculative OCR, vector database,
orchestration, signing or autonomous-compliance stack was added. Existing tests
plus installed test-only browser/axe prerequisites are not third-party repository
security certification. New services, permissions and recurring spend were not
authorized by assumption.

## Reproduce local gates

Install requirements-dev plus Playwright/Chromium and axe-core 4.11.0. Set
`ACCESSDOC_AXE_PATH` and `PLAYWRIGHT_BROWSERS_PATH` if installed outside the repo.
Run `scripts/verify_release.py`, `scripts/self_audit.py` and the loopback gates
listed in docs/LOCAL_STRESS_TESTING.md. UI journey gate:
`node scripts/accessibility_e2e.js` against a locally started service.

Offline mocks are not live model acceptance. Deployment, real humans, sustained
capacity, release authorization, signed provenance, Docker/SBOM/security gates
and non-Linux portability must each be recorded separately; missing gates stay
missing. Exposed credentials require rotation; replacements must not enter
source, public issues, logs or plain-text chat.
