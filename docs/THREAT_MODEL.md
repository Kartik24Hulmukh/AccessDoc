# Threat model

Assets: scanner evidence, client/agency labels, branding image, generated PDF, temporary token, mapping integrity, release integrity.

Trust boundaries: browser → HTTP parser → evidence parser → deterministic catalog → PDF renderer → bounded memory store → token download. No outbound network boundary exists.

Threats: oversized/deep inputs, parser confusion, markup injection, remote/file resource access, cross-request disclosure, token guessing, host/origin abuse, resource exhaustion, log leakage, unsafe mappings/claims, compromised dependencies/workflows.

Controls: strict input/type/depth/count/logo limits; inert escaped text; no dynamic evaluation or remote fetch; random tokens and TTL/byte/item bounds; Host/origin/security headers; time/rate/concurrency bounds; request IDs without evidence logging; deterministic mapping tests; non-root/read-only-ready container; CI and release evidence.

Residual risks: untagged PDF, single-process token store, standard-library server limits, dependency/container advisories, deployment-boundary TLS/monitoring, and human review quality.
