# Security policy

## Supported versions

Only the latest published release receives security fixes during beta.

## Reporting a vulnerability

Use GitHub **Private vulnerability reporting** for the repository. If it is not enabled, do not post exploit details, secrets, personal data, or client evidence publicly; contact a confirmed maintainer through a private channel listed on the repository profile. No email address is invented in this package.

Include the affected version/commit, impact, minimal reproduction using synthetic data, preconditions, and suggested mitigation. We aim to acknowledge within 5 business days and provide a status update within 10 business days; these are goals, not service guarantees.

We coordinate disclosure after a fix or mitigation is available. Credit is optional and requires the reporter’s consent. CVEs are requested when impact and ecosystem distribution justify one. This project does not currently promise a bug bounty.

## Scope

In scope: parser confusion, ReportLab injection, unintended file/network access, cross-request disclosure, token leakage, denial of service bypasses, container/workflow compromise, unsafe mappings or report claims, and public-demo privacy failures.

Good-faith research using synthetic data, minimal load, no persistence, and prompt private reporting is welcomed. Do not access third-party data, disrupt services, retain data, or test social engineering.
