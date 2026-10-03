# Authenticated pilot gate continuation

## Decision

**Not approved for public launch or merge.** Continued from clean source `caed24c37b04bf738dae6594aa316850fd615158`, preserved application/runtime bytes across 59 tracked files, and corrected the operational gate rather than adding unrelated OCR/RAG systems to the scanner-evidence product. The supplied native delivery ZIP and repository catalog match their previous SHA-256 identities; ZIP CRC checks pass. Existing Playwright and axe-core integrations from the catalog remain the relevant validation tools. No new catalog dependency was needed for this gap.

## Frozen failure and measured repair

Before smoke code edits, the shipped verifier ran against the real loopback handler with a synthetic required pilot credential. It failed 17 checks because it never sent application authorization. The existing scoped test file passed 11 tests/9 subtests, demonstrating an uncovered gate defect—not a production failure measurement.

The repaired runner passes **47 functional checks** against that authenticated loopback handler, including missing/wrong app credential rejection, readiness, full synthetic deployed SHA before/after, ZIP verification, receipt, errors and hosted UI contracts. The final focused suite passes **17 tests/12 subtests**. Source/static URL and redirect boundaries prevent both credential classes from being sent to arbitrary projects; reflected secrets are redacted, and failed setup overwrites stale success artifacts. SSO302 fails authorization immediately with zero application checks.

The first full continuation run failed 15 existing browser tests because Chromium was absent from this resumed environment (930 passed). The failure receipt is retained. Restoring the required Playwright browser—not weakening or skipping those tests—produced **945 passed, one deployed-target skip, 214 subtests**, and the three intentional duplicate-ZIP warnings. All ten local release-verifier gates pass; unchanged version/BOM/config lints and diff whitespace validation pass. Installation recovery is not a code performance gain. Prior latency/RAM/load/provider evidence remains historical, not a fresh production benchmark.

## Five-point release premortem disposition

| Risk | Continuation action | Remaining evidence |
|---|---|---|
| Authenticated pilot falsely appears broken or unprotected | Separate app Bearer from platform bypass; real handler positive/negative tests; required auth in hosted workflow | Exact protected deployment execution with actual matching secrets |
| Secret-bearing workflow runs without reviewed authority | Created protected verification environment, owner review, admin bypass disabled, two allowed branches | Accepted operator review; independent security/release review is separate |
| Documentation invents provider CPU/memory/time limits | Corrected absent 60-second claim and actual legacy handler architecture | Authorized platform settings, fleet/spend controls and termination/soak drills |
| Synthetic tests are counted as users or legal signatures | Cumulative genuine ten-person protocol, five-practitioner subgroup, consent and authenticated exact-artifact assent forms | Actual people, booking acceptance, observed results, qualified reviewer decisions |
| Handoff overstates accessibility or integrity | Scoped HTML claims; unsigned hash matching does not establish origin/truth/assent | Independent assistive-technology and claims/legal reviews |

Previously measured native deadline, token, report quota and idle-expiry controls are unchanged. Large-file/OCR/general-document workflows are not certified by this scanner-evidence application or this continuation.

## Actual GitHub coordination performed

Created `accessdoc-pilot-verification`: required reviewer `Kartik24Hulmukh` (the sole current repository collaborator), admin bypass disabled, allowed branches `main` and `harden/accessdoc-v1-launch`. Self-review is allowed so the sole operator can authorize a verification run; this **does not claim independent approval**. No environment secret was provisioned, no protected job was approved, and no deployment was promoted.

Created repository-owner coordination requests:

- [Deployment controls and protected verification](https://github.com/Kartik24Hulmukh/AccessDoc/issues/96)
- [Ten genuine practitioner sessions and independent accessibility review](https://github.com/Kartik24Hulmukh/AccessDoc/issues/97)
- [Named security, legal and release-owner assent](https://github.com/Kartik24Hulmukh/AccessDoc/issues/98)

These are actual open issues assigned for coordination—not bookings, recruited participants, accepted roles, signatures or passed gates. The AI SRE/founder reviews are not real-human evaluations. The protocol reuses supplied research, rejects unsupported traction/legal claims, and requires private consent/identity storage with safe public summaries.

## Deployment authority check

Rechecked the exact historical candidate preview `https://access-4hilaq97t-atlas16.vercel.app`, deployment `6769085576`, with expected source `caed24c37b04bf738dae6594aa316850fd615158`. GitHub reports deployment success, but the app is behind protection: authorization failure, **zero functional checks**, no observed application SHA. The report's elapsed time is 0.067 seconds; this is authorization classification, not application recovery.

Vercel's official OAuth connection was requested; both attempts returned declined (the second followed the user's explicit retry request). Do not retry automatically. A separate authorized client-credentials exchange using the supplied OAuth application credentials returned HTTP400 `invalid_client`; no access token or project access was granted. Credential values are excluded from this repository/evidence. GitHub admin permission does not substitute for Vercel authority or a person's review assent.

## Required next authority and actions

1. Authorize a supported Vercel connection or provide valid project-scoped access through a secure mechanism; provision matching pilot/bypass secrets privately. Do not send more secrets in public issues or source.
2. An authorized operator verifies platform fleet/invocation/edge limits, actual spend ceilings, collector/alerts and privacy controls, then performs exact-target smoke, approved staging soak and immutable rollback rehearsal.
3. Consenting people accept coordinator/reviewer responsibilities, complete the ten-person protocol and independent accessibility review, and return genuine security/legal/release decisions tied to the final artifact/deployment.
4. Rotate credentials disclosed in chat. Keep PR95 draft and auto-merge disabled while target or human gates remain pending. No claim of production readiness, human participation, general OCR ingestion, production capacity, actual traction or launch follows from local green checks.

Raw scoped receipts and hash manifest are in `docs/evidence/pilot-gates-2026-10-02/`. The original browser-environment failure and synthetic before/after remain visible; target/approval blockers are not converted to successful statuses.

## Follow-up adversarial metadata check

After the first repair was committed, a synthetic hostile health response demonstrated that stdout redaction alone was insufficient: an invalid `commit` field could reflect the synthetic pilot credential into the JSON artifact. The frozen before report contains only the deliberately synthetic canary, not a real credential. This remained a failing readiness run, but artifact secrecy still required repair.

The first follow-up runner recorded only complete SHA-shaped deployment identities that are not equal to either credential. The before/after real-loopback reproduction changes `synthetic_credential_in_report` from true to false; neither run passes readiness or executes application checks. A new regression uses a forty-character hexadecimal synthetic credential, so the fix cannot rely solely on rejecting malformed SHA syntax. The focused suite now passes 18 tests/12 subtests. This follow-up changes validation tooling only, not the 59 application/runtime files. The 945-test full receipt above is the earlier candidate's historical result; final exact-head full-suite and hosted CI receipts are recorded separately in the delivery capsule and PR update, rather than inferred from it.


## Independent substring and representation review

The independent read-only SRE review found the first metadata patch incomplete: a 32-hex synthetic credential embedded in a 40-hex health commit still entered the artifact, and an uppercase 40-hex reflection entered both artifact and stdout. Reproducible old-commit and new-working-tree loopback receipts preserve both failures.

The current runner instead archives only a match to the independently supplied expected commit. It omits all unexpected health metadata and raw response/verifier details from logs, and applies case-insensitive credential defense to known strings and report serialization. The expanded real-loopback cases cover whole-hash, substring, uppercase and quoted metadata across commit/version/status; 18 focused tests and 16 subtests pass. Independent mocked reruns of all four representations also fail closed without the tested leaks (9 targeted tests/13 subtests; 9 deselected). These are synthetic probes, not evidence of a real credential exposure or a deployed application check.

The resumed machine later lost its home-directory Playwright cache again, producing the same 15 browser-test failures. Required browser binaries are now installed under retained `/data` with an explicit test-runtime path; this is environmental restoration, not test suppression or an application fix. Final exact-commit full-suite and hosted CI receipts belong to the delivery capsule/PR update; earlier full-suite counts remain historical.
