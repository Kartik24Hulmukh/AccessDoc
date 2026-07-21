# Architecture

Browser UI → bounded HTTP adapter → parser/normalizer → deterministic WCAG catalog → immutable request model → ReportLab renderer → bounded in-memory TTL store → random-token download.

The process makes no outbound requests and stores no accounts or original evidence. `app/parser.py`, `catalog.py`, `models.py`, and `reporter.py` are domain/service layers; `app/main.py` is the HTTP/runtime adapter. The standard-library threaded server is appropriate for local and constrained single-replica deployments behind a hardened reverse proxy; it is not claimed horizontally scalable. A future ASGI adapter must preserve the v1 contract and domain tests.
