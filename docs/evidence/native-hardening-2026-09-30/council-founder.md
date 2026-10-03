# AccessDoc — read-only founder/product council audit

**Baseline:** `/data/AccessDoc`, HEAD `78736f2` (confirmed). 2026-09-30 UTC.

## Decision

Keep the launch scoped to a **source-only, supervised practitioner handoff**. The documented local CLI bundle → verify → HTML delivery path worked with a supplied synthetic fixture. The browser experience has three reproducible gaps that can undermine a practitioner's trust or mix client/evidence context. Fix those before treating browser completion as a reliable end-to-end handoff.

This is one agent's founder/product review, not a council of independent humans. Local browser fixtures and one CLI fixture are synthetic checks, not ten practitioner sessions, 100 humans, recipient acceptance, repeat-use evidence, or traction evidence. No multiplier or broad-launch claim is established.

## Scope and method

- Inspected `public/static/app.js`, `public/index.html`, `examples/agency-handoff/README.md`, `cli.py`, relevant `app/scan.py` paths, bundle/remediation adapter source, and existing evaluation/claims/release/privacy/HTML documentation and browser-journey test source.
- No broad market research; existing practitioner-launch framing applied rather than re-researched.
- No repository edits, dependency installs, deployments, shared-browser launch, live site scan, provider calls, credential reads, private-data reads, or inspection of stored tool-result files.
- Used existing Python Playwright with a separate local headless Chromium. Every browser URL was intercepted and fulfilled with source assets or synthetic responses; no application server or external endpoint was contacted. ZIP responses in UI tests were deliberately synthetic bytes: these checks validate state transitions, **not real UI ZIP integrity**.
- Separately generated a real bundle locally from `fixtures/axe-sample.json`, with `/data/accessdoc-venv/bin/python`, fixed audit date, and `--sarif --vpat --eaa`; `cli.py verify` returned `valid: true`, `errors: []`, exit 0. No enrichment was requested.
- Reproduction harness: `/data/accessdoc-turn5-checks.py`, outside the repository. Storage fallback is explicitly excluded and remains with the main lead.

## 1. P1 — Bind every action to one evidence revision

**User case:** A practitioner uploads export A, generates a bundle, then requests guidance or loads a sample while preparing another handoff.

**Source:** `public/static/app.js:1` uses a nonempty uploaded file in preference to the textarea. The sample handler fills the textarea/client/agency but never clears the file. Line 2's remediation handler reads only the textarea, not the file or the evidence that generated the bundle. Neither regeneration nor input changes clear the previous remediation output.

**Reproduction and observed result:**

1. Fill client/agency; upload synthetic `image-alt` JSON with an empty textarea; generate successfully using a mocked ZIP response.
2. Click **Get AI remediation plan**. Zero remediation requests occur. The error reads **“Report not generated”** and **“Paste or upload scanner evidence…”**, even though a file was uploaded and the bundle result is present.
3. Leave that file selected; click **Load sample evidence** (mock sample contains `label`); generate again. The visible textarea contains B and sample client details, but bundle payload still contains A (`image-alt`, filename `synthetic-a.json`).
4. Request remediation. Its payload contains B (`label`), not the bundled A.
5. Generate another bundle. The prior remediation output becomes visible again without being refreshed.

**Why it matters:** A reviewable handoff cannot silently combine one scan's report with another scan's plan or sample client identity. This is a context/integrity workflow defect, not a catalog-quality problem.

**Smallest coherent fix:** Centralize effective-evidence selection and capture an immutable evidence/client revision for generation. Have remediation use that same revision, including uploads. Loading sample evidence must explicitly clear or replace uploaded evidence. Invalidate existing guidance whenever that revision changes. Use action-specific error headings so a remediation error does not falsely say the report was not generated.

**Acceptance case:** File-only generation followed by remediation works; upload A → load sample B yields B everywhere; editing/replacing evidence makes old guidance unavailable or explicitly stale. Browser tests assert request evidence, source filename and revision, not merely that a download happened.

## 2. P1 — Make pending/repeated work recoverable without destroying the last good download

**User case:** A practitioner has a valid bundle, retries with a bad file, or realizes during generation that the wrong client is selected.

**Source:** `public/static/app.js:1` hides `result` and calls `clearBundle()` before validation or reading the replacement file. Fetches and the 429 retry timer have no abort signal, cancellation control or revision guard. Only Generate is disabled; sample and input controls remain available. `public/index.html` has no Cancel or Reset/New report control.

**Reproduction and observed result:**

- After a successful mocked generation, Download ZIP again has a blob URL. Upload 2,000,001 bytes and submit. Local size rejection occurs, but the previous download `href` becomes null and the result is hidden. A failed replacement has destroyed the prior in-page recovery path.
- Hold a mocked bundle response pending. Generate is disabled; there are zero Cancel/Reset controls; Load sample remains enabled. Submit under **Synthetic Pending Client**, then load the sample. The form now shows **Northstar Community Bank**. Release the old response: the old result is displayed and automatically downloaded under the changed form, without a visible client/evidence identity confirming what was generated.

**Why it matters:** In repeated agency handoffs, the user needs to stop or supersede work and know which client a returned artifact belongs to. Reloading is not a usable reset: it loses both entered data and the recoverable download.

**Smallest coherent fix:** Keep the last successful artifact until a replacement succeeds. Add explicit Cancel and New report/reset behavior, using AbortController plus a generation token guarding late responses, file-read completion and retry timers. Label the result with the submitted client and evidence source. Cancel should stop browser waiting/retrying; it must not promise that already accepted server work was rolled back. Reset should clear sensitive form data, files, guidance and download URLs deliberately, not on a failed submit.

**Acceptance case:** Successful A → oversized/corrupt B retains A's labelled download; cancel during response wait or 429 delay produces no later download or retry; reset clears evidence, API-key field and outputs; A pending → B selected cannot display A as B. Repeated download remains available until explicitly reset or replaced successfully.

## 3. P1 — Correct the optional model data-sharing disclosure before consent

**User case:** A practitioner may use a client export locally but cannot send client identity or DOM selectors to an external model provider.

**Source:** `public/index.html` promises remediation sends **“only rule IDs, impact, node counts and help text”** to the model gateway. `app/remediate.py:extract_violations` also extracts the first node's `target` (up to 120 characters); `build_prompt` includes it and the supplied client name (up to 80 characters). The browser posts the full parsed scanner object plus client name to the same-origin remediation endpoint; the server then derives the model prompt. Those are two different data-flow boundaries.

**Local reproduction:** Call only the pure `extract_violations` and `build_prompt` helpers with synthetic `#synthetic-a` and **Synthetic Client Sentinel**. Both occur in the generated prompt. No gateway object or chat method was invoked and no provider was contacted.

**Why it matters:** A selector may contain names, IDs or sensitive route/state context, and a client name can itself be confidential. Truncation/control-character cleaning is not redaction. A disclosure using “only” must match the actual outbound fields.

**Smallest coherent fix:** For this launch, omit client name and node targets from external prompts by default; retain them locally only if needed. If opt-in sharing is retained, disclose the exact fields before the action and make the consent meaningful. Clearly distinguish deterministic local bundle generation, same-origin receipt of the full scan, and optional external-model processing. Align `docs/PRIVACY.md`'s default-build “no outbound request…model” wording with the optional configured remediation path; it must not read as a blanket promise about that feature. Do not alter storage fallback in this workstream.

**Acceptance case:** Use sentinel client names and selector values in a mocked gateway test to assert they are absent by default, or present only after explicit opt-in with matching disclosure. Confirm no model invocation for the deterministic bundle path. Validate both configured-model and offline modes, not just a successful advisory response.

## Existing launch/evaluation boundaries — not additional fix requests

- The agency handoff example correctly scopes scanning to one authorized page, requires local pinned axe, warns about authenticated/interactive states, requires review metadata outside the bundle, and directs recipients to HTML. Static inspection of `app/scan.py` supports the optional browser/axe dependency and initial-page scan framing; no live scan was performed here.
- `cli.py verify` makes the right distinction: matching generation-time hashes do not authenticate scan completeness, browser state, human review, signer identity or legal acceptance. The browser result lists the manifest but does not guide users through the CLI verify command. For the current source-only launch, make the example handoff the supervised onboarding path; do not equate browser “generated” with independent verification.
- `docs/EVALUATION_PROTOCOL.md` evaluates narrative PDF creation/correction; the handoff example and current UI treat semantic HTML as primary and PDF as an untagged convenience copy. Existing ten-session gates are planned human evaluation criteria, not evidence supplied by this audit. Any execution of that study must measure the actual HTML/ZIP/verify/review/recipient workflow rather than substitute synthetic success counts for people.
- Existing `scripts/browser_journeys.py` checks file-only generation, immediate resubmission, corrupt/oversized uploads, clearing a file and sample recovery. Its sample test runs **after clearing the file**, so it does not cover the mixed-evidence reproduction above. It also does not establish cancellation, reset, prior-download survival or guidance/evidence identity.

## Recommended order

1. Evidence revision consistency: prevents wrong-context report/plan handoffs.
2. Pending/repeated-work lifecycle: prevents stale output and loss of recoverability.
3. Exact external-data disclosure/default minimization: prevents consent based on an inaccurate promise.

These are three bounded workflow fixes. Successful synthetic acceptance checks would establish implementation behavior only. The next product proof remains an observed, consented practitioner handoff and recipient action, with correction effort and a second handoff request recorded—not a new market study or a growth promise.
