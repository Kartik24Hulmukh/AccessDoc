# Release checklist

- [ ] Confirm legal owner, maintainers, private security route, repository URL, and distributable fixtures/assets.
- [ ] Clean protected branch; independent review; version/changelog/citation updated.
- [ ] Compile, all tests, browser mobile/desktop, PDF extraction/visual/active-content, hostile input, deterministic mappings, and commerce-absence checks pass.
- [ ] Secret/dependency/container/license scans reviewed; SBOM and provenance generated in CI.
- [ ] README limitations, privacy, threat model, API and deployment docs match behavior.
- [ ] Build once from tagged commit; verify archive contents/checksum and clean install.
- [ ] Deploy exact digest to staging; HTTPS/header/load/alert/rollback checks pass.
- [ ] Named security and accessibility reviewers approve exact artifact.
- [ ] Publish immutable tag/release; attach source, checksum, SBOM, evidence; post-release smoke passes.
