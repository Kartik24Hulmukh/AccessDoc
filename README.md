# AccessDoc

**Open-source scanner evidence → reviewable client handoff.**

AccessDoc is for accessibility consultants and agencies who already have axe-core results and need a branded, claims-limited evidence report. It normalizes supplied evidence, applies a deterministic reviewed WCAG 2.2 mapping catalog, keeps unknown rules unresolved, records manual observations, and embeds a cryptographic evidence receipt.

> **Beta:** Not a scanner, certification, conformance determination, legal opinion, or substitute for knowledgeable human testing. PDF/UA conformance is not asserted.

![Verified local UI](artifacts/ui-desktop.png)

## Why it is different

- Evidence you already have; no duplicate scan.
- Axe-core is the documented golden path; Lighthouse, WAVE JSON/CSV, and text are beta adapters.
- Deterministic catalog instead of model-generated normative mappings.
- Unknown rules remain **Unmapped — manual review required**.
- Automated findings, manual observations, limitations, and provenance remain distinguishable.
- Evidence receipt records source filename, input SHA-256, detected format, generator/catalog versions, and mapped/unmapped counts.
- Default local runtime makes no outbound requests and persists no original evidence.

No individual feature is unique. The product hypothesis is that this combined evidence-safety contract reduces practitioner editing and claims risk. That hypothesis is unverified; see `launch/PRACTITIONER_PROTOCOL.md`.

## Five-minute local path

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m app.main
# open http://127.0.0.1:8000 and select “Load sample evidence”
```

Or:

```bash
docker compose up --build
```

## Verify

```bash
make test
make verify
```

Verified release evidence must identify the exact archive SHA, file count, test count, browser result, PDF checks, and grep gates. A local pass does not establish hosted-service security or availability.

## API and operations

- `POST /api/v1/generate` — stable v1 generation endpoint.
- `GET /api/sample` — synthetic axe fixture.
- `GET /download/{token}` — temporary report download.
- `GET /health/live`, `/health/ready`, `/metrics`, `/version` — operations.

See `docs/API_V1.md`.

## Privacy and safety

No accounts, analytics, model calls, external fetches, or original-evidence persistence exist in the default build. Inputs and outputs can still contain sensitive client material. Do not submit confidential or regulated data to a public demo; sanitize evidence or self-host.

## Wednesday release decision

The package supports a controlled practitioner OSS beta, not a broad hosted-service launch. Read:

- `launch/WEDNESDAY_DECISION.md`
- `launch/BASE_RATE_10.md`
- `launch/COMPETITOR_MATRIX.md`
- `launch/PRACTITIONER_PROTOCOL.md`
- `launch/OUTREACH_20.md`
- `launch/PERSONA_SIMULATION.md`
- `launch/POST_LAUNCH_SCORECARD.md`

## Project policies

[Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Support](SUPPORT.md) · [Governance](GOVERNANCE.md) · [Claims](docs/CLAIMS_POLICY.md) · [Privacy](docs/PRIVACY.md) · [Threat model](docs/THREAT_MODEL.md)

Apache License 2.0. See `LICENSE` and `THIRD_PARTY_NOTICES.md`.

## Verify an input receipt offline

Download the JSON receipt with the PDF and retain the exact submitted UTF-8 input text. Then run:

```bash
python scripts/verify_receipt.py receipt.json submitted-input.txt report.pdf
```

This verifies file correspondence only. It does not authenticate the source, validate findings, or establish accessibility conformance.


## Vercel deployment

This release includes a stateless Python Function at `api/bundle.py` and static UI in `public/`. Import the GitHub repository into Vercel with the **Other** framework preset; do not set a build command or output directory. Start with a protected preview and follow `docs/VERCEL_DEPLOYMENT.md`. The direct endpoint is `POST /api/bundle` with JSON and returns `application/zip`.

Repository tests and package verification do not constitute an actual Vercel deployment receipt. Do not operate an unrestricted public upload service until the external security, privacy, abuse, ownership, and review gates in the runbook are complete.
