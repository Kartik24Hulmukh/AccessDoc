# Turn 5 — scoped UI implementation handoff

## Outcome
Implemented the founder-audit browser fixes in `/data/AccessDoc` on `harden/accessdoc-v1-launch`, without staging or committing. Owned changes only:
- `public/static/app.js`
- `public/index.html`
- new `tests/test_hosted_ui_revision.py`

Other files changed concurrently by sibling/parent workstreams; none were edited, reverted, stashed, or reset here. No dependency installs, provider requests, credential/deployment file reads, shared-browser use, or broad research.

## Frozen before evidence (outside repository, captured before edits)
`/data/accessdoc-turn5-ui-before/` contains the original `app.js`, original `index.html`, `SHA256SUMS`, `reproduce.py`, `regression-evidence.json`, and `regression-stderr.log`.
The reproduction uses intercepted **loopback** URLs and explicitly synthetic, invalid ZIP bytes, not a server/provider integration. It observed:
- uploaded file-only bundle -> zero remediation posts and misleading report error;
- selected A upload + sample B -> A bundle but B remediation;
- old guidance still visible after regeneration;
- oversized replacement discards the successful download;
- no cancel/reset controls;
- pending old-client response displayed after sample/client change.

## Implementation decisions
- A monotonically increasing page-local revision covers all form input/change events (including evidence upload/replacement, client/agency/date/manual findings, format and key changes). Generation snapshots all values/files **before** asynchronous reads.
- One central effective-evidence reader gives selected uploads precedence, including explicit rejection of empty files rather than silently substituting textarea data. Size and file-read completion are guarded.
- Remediation uses the immutable scanner/client/source/revision retained from the **last successful bundle**, not a freshly mixed textarea/client. Credentials are not retained in that successful artifact record. Changed inputs erase guidance and disable remediation until a matching new bundle succeeds.
- Sample loading clears the evidence upload, restores textarea-required validation, updates filename labels, and invalidates guidance. A delayed sample cannot override intervening edits or a reset.
- Preserve the last successful blob URL/result until a replacement actually succeeds. Failed corrupt/oversized replacements leave its labelled client/source/revision download available. Old outputs explicitly say they belong to the previous report when inputs change.
- Single active operation uses AbortController; immutable revision + operation-identity guards block stale presentation after every asynchronous boundary. Abort cancels fetches, retry timers, FileReader, and waiting for File.text (whose underlying browser read is not abortable).
- Native accessible **Cancel** and **New report** controls reuse existing visual classes. Cancel stops browser waiting/retries without claiming server rollback. New report aborts pending work, clears private fields/API key/files/guidance/summary/errors, revokes the download URL, and focuses Client name. The non-private date defaults to today.
- Action-specific error headings for sample/remediation. Summary values are rendered through DOM text nodes rather than interpolating response headers as HTML.
- Disclosure distinguishes the full scan/client payload received by the same-origin server from optional external processing. It states optional model fields (rule IDs, impact, node counts, help text), possible private content, default omission of client names/selectors, and that omission is not complete redaction. Deterministic generation does not call a model. **Backend minimization is parent-owned and must land together with this disclosure.**

## Scoped validation
Executed with `/data/accessdoc-venv/bin/python`, local headless Playwright and an actual `app.main.Server` loopback bundle endpoint. No full suite run.

Passing command:
```
/data/accessdoc-venv/bin/python -m unittest tests.test_hosted_ui_revision tests.test_hosted_ui tests.test_narrow_viewport.NarrowCssContractTests -v
```
Result: **12 tests passed, zero skips**, in 32.256 seconds. `/data/accessdoc-turn5-ui-scoped-pass.log`.
- Seven new regression tests exercise upload-only evidence/guidance identity, actual verified ZIP integrity, sample clears upload, guidance invalidation, failed replacement retaining a real verified download, cancellation/late replies/client changes, cancellation during 429 timer, delayed file-read guard, sensitive reset, and delayed guidance discarded on evidence change/reset.
- Remediation responses, late network responses, 429s and file-read delays are **synthetic state controls**; they do not validate a provider or real remediation service. Late synthetic bundle responses are deliberately not ZIPs and must never become downloads.
- Successful bundle requests and redownload are **real**, not mocked. `validate_bundle` verifies the generated/downloaded bytes. Evidence/source/client request bodies and revision labels are asserted.
- Existing authenticated sample/error recovery and file-only/recovery UI tests pass. The existing axe UI check reports no violations and asserts the production CSP without unsafe-eval/unsafe-inline; instrumentation alone bypasses CSP.
- Three existing viewport/CSS contracts pass. Live narrow-viewport study, full suite, external provider behavior, practitioner sessions, and recipient acceptance were not run or claimed.

Additional passing logs:
- `/data/accessdoc-turn5-ui-js-check.log`: `node --check public/static/app.js`.
- `/data/accessdoc-turn5-ui-diff-check.log`: scoped `git diff --check`.

Preserved failed development logs:
- `/data/accessdoc-turn5-ui-scoped-first.log`: test harness callback bug (Playwright cannot wrap builtin list.append directly), causing cascading setup failures; fixed with lambdas and robust cleanup registration.
- `/data/accessdoc-turn5-ui-scoped-second.log`: 6/7 pass; one sample assertion compared raw textarea trailing newline to intentionally trimmed generation input; fixed assertion to `.strip()`.

## Handoff boundaries
Parent should inspect the three assigned files and commit with coordinated backend minimization. UI tests establish bounded browser state transitions and real local bundle integrity, not independent scan completeness, human review, legal conformance, provider readiness, or product traction. Reset clears this page, not already downloaded copies or accepted server work.
