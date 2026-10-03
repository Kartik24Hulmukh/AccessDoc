# Turn 6 final targeted smoke review

**Reviewed HEAD:** `69b2b8a8668fee171e83c1159880efe37457ba00`; repository clean and unchanged. Scope: `scripts/production_smoke.py` and `tests/test_release_validation_integrity.py`. No secrets, external requests, repo edits, full-suite run, or renewed platform research. Synthetic tests used an empty environment plus explicit nonsecret fixtures; custom repro mocked the HTTP opener (zero network).

## Result: one concrete high-priority secrecy defect remains

**Paths/lines:** `scripts/production_smoke.py:118–128, 188–191`; regression gap in `tests/test_release_validation_integrity.py:test_reflected_untrusted_commit_cannot_leak_into_artifact`.

The metadata guard requires a 40-hex string and excludes only **exact, case-sensitive whole-string** credential equality. A shorter hex credential embedded in a valid-length hex commit is still written verbatim to `observed_commit` in the JSON report. Since reports are archived even on failure, failing the exact-SHA gate does not protect the secret from artifact readers. This is the same reflected-metadata threat model as the just-added fix, not a new requirement to trust arbitrary origins.

**Confirmed mocked repro:** application credential is a synthetic 32-hex value (`deadbeef` repeated four times); health reports that value followed by eight hex digits as `commit`; expected SHA is a different 40-hex value. Smoke exits **1**, report `pass=false`, but the report retains the entire reflected value and contains the literal credential. Stdout redaction succeeds for this particular case; artifact secrecy does not.

**Second confirmed representation gap:** a synthetic lowercase 40-hex credential reflected as uppercase passes the guard and appears in both `observed_commit` and stdout. The literal lowercase bytes are absent, but the credential is trivially recoverable. This is not an exact-SHA false pass: the expected SHA differs and smoke fails.

**Recommended minimal safe direction:** do not persist or print unexpected health-provided metadata strings. Record fixed outcome categories / identity-match booleans; for an observed identity, retain only a match to the independently supplied expected SHA, with configured credential collisions rejected. Remove raw health `commit`, `adapter_version`, and `status` interpolation rather than relying on replacement after `repr()` or arbitrary upstream encoding. Keep full exact-SHA comparison for readiness and final verification. A JSON string replacement would cover the literal-substring case but would not completely solve recoverable encoded reflections.

**Add targeted tests:** (1) 32-hex credential embedded in otherwise valid 40-hex commit; (2) uppercase reflection of a 40-hex credential; (3) unexpected metadata strings using escaped/quoted representations. Assert no raw or recoverable reflected credential in JSON/stdout/stderr, `pass=false`, and no network beyond the mocked/loopback fixture. Existing whole-40-hex equality regression should stay.

## Confirmed boundaries / checks

- Ran **9 focused tests**, **9 deselected**, **9 subtests passed**, in 0.56 seconds using `/data/accessdoc-venv/bin/python`; no full suite or artifact-generation tests ran. Initial system-Python pytest attempt failed because pytest was absent; no installation performed.
- Covered target-origin restrictions, full-SHA collision rejection, cross-origin redirect rejection, separate platform/application headers, missing required pilot credential, redaction helper, unsafe-target stale-report replacement, SSO302 immediate authorization failure, and exact whole-credential metadata rejection.
- Bearer auth and negative-auth checks are present. Platform bypass remains during auth-negative requests; app auth is omitted/invalidated separately. GETs do not initially receive application auth.
- Redirect handler compares scheme/host/effective port before allowing redirection, preventing either credential from reaching a different origin. SSO302 is now immediately classified as authorization failure; no redirected Location query is emitted by that path.
- Readiness and post-smoke identity checks still use full 40-character SHA equality; seven negative-response contracts remain. CLI runtime exception fallback overwrites the report for the workflow's explicit `--output PATH` invocation.

**Conclusion:** the earlier missing-Bearer and SSO classification defects are closed in the reviewed code. The expanded whole-40-hex regression passes, but it does not close reflected credential **substring/representation** leakage. Fix this artifact/log boundary before treating credential-bearing smoke evidence as safe to archive. No launch or deployment approval is implied.

## Working-tree recheck — findings closed for reproduced cases

Parent's scoped uncommitted fixes were re-inspected and tested on top of HEAD `69b2b8a8668fee171e83c1159880efe37457ba00`. At inspection, only `scripts/production_smoke.py` and `tests/test_release_validation_integrity.py` were modified by the parent; this review made no repository changes.

**Actual rerun:** same focused selection: **9 passed, 9 deselected, 13 subtests passed in 1.04 seconds**, using the existing virtualenv, empty inherited environment, bytecode disabled and pytest cache provider disabled. The expanded regression now includes whole-40-hex, embedded-32-hex, uppercase-40-hex and quoted metadata cases across health status/version/commit.

**Independent mocked reruns (no network):**

| Synthetic reflected metadata case | Exit | Report pass | Observed commit | Credential leak in JSON/stdout/stderr |
| --- | --- | --- | --- | --- |
| 32-hex credential embedded in 40-hex commit | 1 | false | null | No |
| Uppercase reflection of lowercase 40-hex credential | 1 | false | null | No |
| Exact whole-40-hex credential reflection | 1 | false | null | No |
| Quoted/encoded credential in status/version; invalid commit | 1 | false | null | No |

Leak assertions tested both case-insensitive literal and JSON-escaped credential forms. The first two cases reproduce the precise scenarios that previously leaked; both now fail closed without retaining the upstream value. Current readiness records only the independently expected SHA when matched and noncolliding, and health diagnostics emit fixed match booleans rather than untrusted metadata. Artifact serialization adds case-insensitive redaction as defense in depth.

**Updated conclusion:** the substring and uppercase leakage findings above are **closed in the reviewed working tree for all reproduced cases**. No remaining severe defect was demonstrated by this targeted rerun. This is not verification of a future commit, full functional smoke/full suite, deployed behavior, arbitrary encoding secrecy, or release approval. No external calls, secrets, full-suite execution, or repository edits were performed.
