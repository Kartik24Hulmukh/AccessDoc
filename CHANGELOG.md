# Changelog

## 0.4.0-beta.4 — Vercel source candidate

- Added a stateless Vercel Python handler at `api/bundle.py`.
- Added one-request ZIP delivery with PDF, standalone semantic HTML, receipt, and integrity manifest.
- Added Vercel configuration, Python pin, no-store controls, serverless tests, cold-start and concurrency checks, and deployment/Gumloop runbooks.
- Preserved local/container mode and the legacy token API for compatibility.


## [Unreleased]

### Fixed
- Both hosted adapters now route stdlib `send_error` (400/414/431/501 parse rejections) through the JSON error contract: security headers, `X-Request-ID`, no HTML, no reflection of the client request line, no Python/BaseHTTP server banner. Self-hosted request logs record the real status instead of 500 for these rejections.
- Serverless adapter exposes `GET /limits` (parity with self-hosted) including `api_key_required` and `max_concurrent_requests_per_process`.

## [0.4.0] - 2026-07-21

### Added
- Cryptographic evidence receipt in API, UI and PDF.
- Evidence-first launch overlay, 10-project base rate, competitor matrix, practitioner protocol, 20 direct outreach drafts, persona simulation and kill rules.
- War Room Gumloop prompts, claims/privacy/operator notes and issue templates.
- Mechanical banned-word, placeholder, stale-file and immutable-Action gates.

### Changed
- Public framing from assessment to accessibility evidence report.
- PDF/UA limitation moved beside download.
- Browser evidence paths made repository-relative.
- Workflow Actions pinned to immutable commits.

### Fixed
- Removed stale release evidence and cache files from the release candidate.
- Aligned runtime, package and evidence versions.

## [0.3.0] - 2026-07-19

- Open-source beta baseline with deterministic mappings, bounded memory lifecycle and community files.
