# Gumloop chat prompt — Wednesday AccessDoc beta

```text
Run the AccessDoc Wednesday practitioner-beta release workflow.

Source archive: {{source_archive}}
Authorized SHA-256: {{authorized_sha256}}
Repository and base branch: {{repository_url}} / {{base_branch}}
Overlay branch: {{overlay_branch}}
Release owner: {{release_owner}}
Security owner/private channel: {{security_owner_and_channel}}
Accessibility reviewer: {{accessibility_reviewer}}
Target environment: {{local_or_staging}}
Target image digest: {{image_digest_if_any}}
Practitioner outreach list: {{consented_target_list}}

Start read-only. Verify safe ZIP entries, hash and baseline tests. Stop on mismatch. Read launch/WEDNESDAY_DECISION.md and enforce its go/no-go. Open a PR for the launch overlay; do not merge or publish. Run all mechanical gates and attach receipts. Keep naming changes in a separate later PR. If a hosted target exists, verify exact digest, HTTPS, headers, limits, alerts and rollback; otherwise mark target verification NOT_RUN. Draft 20 individualized messages for human approval; never mass-send or include client evidence. Return the three maturity ledgers, adoption ledger, blockers, kill-rule status and checksummed handoff bundle. Do not infer traction from stars, visits or downloads.
```
