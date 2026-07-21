# Production readiness

## Locally verified
Compilation, unit/HTTP/security tests, browser journey, PDF generation/extraction/visual review, hostile-input bounds, commerce-absence regression, health/readiness/metrics/version, structured logs, and graceful shutdown.

## Required for a public service
Exact commit/image digest; HTTPS/HSTS and external header scan; reverse-proxy request limits; central logs/metrics/alerts; load and failure testing; rollback rehearsal; dependency/container scans and SBOM; independent security and accessibility review; named approval. Persistent multi-user operation additionally requires identity, tenant isolation, managed storage, retention, backup, and restore.

The current standard-library server is supported for local and constrained single-replica deployments behind a hardened proxy, not claimed horizontally scalable.
