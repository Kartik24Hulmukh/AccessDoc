# Deployment runbook

1. Verify source/archive SHA and safe extraction.
2. Import to the authorized repository; record commit.
3. Run all tests/scans; build once; record immutable image digest/SBOM.
4. Human approval → deploy exact digest to staging.
5. Configure exact hosts/origins, HTTPS/HSTS, proxy body/header/time/connection limits, one replica, read-only root, bounded tmpfs, no egress.
6. Run health, version, sample generate/download, PDF, external header, load, alert, and failure checks.
7. Rehearse rollback to prior digest and restore the candidate.
8. Obtain independent security/accessibility and named release approval.
9. Promote exact staging digest; run safe smoke; preserve evidence.
