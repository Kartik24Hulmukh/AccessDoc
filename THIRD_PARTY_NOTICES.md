# Third-party notices

## Scope and version provenance

This inventory describes the measured application runtime dependency candidate for source commit `16a527cccb6974d846a83de30fbfaf384dda13c3`, captured on Linux x86_64 CPython 3.13.14. It is not proof of the package contents or interpreter version of any deployed container. The paired `sbom.json` is a local dependency snapshot, not a deployable-artifact or production SBOM; it is deterministic, generated from that 19-package closure, and explicitly excludes installer, test, optional scanning and signing tooling.

## Application runtime dependencies

| Component | Measured version | Declared license |
|---|---|---|
| aiodns | 3.6.1 | MIT License |
| aiohappyeyeballs | 2.7.1 | Python Software Foundation License |
| aiohttp | 3.14.3 | Apache-2.0 AND MIT |
| aiosignal | 1.4.0 | Apache Software License |
| attrs | 26.1.0 | MIT |
| certifi | 2026.7.22 | Mozilla Public License 2.0 (MPL 2.0) |
| cffi | 2.1.1 | MIT-0 |
| charset-normalizer | 3.5.2 | MIT |
| frozenlist | 1.8.0 | Apache-2.0 |
| idna | 3.20 | BSD-3-Clause |
| multidict | 6.9.1 | Apache License 2.0 |
| pillow | 12.3.0 | MIT-CMU |
| propcache | 0.5.4 | Apache-2.0 |
| pycares | 4.11.0 | MIT License |
| pycparser | 3.0 | BSD-3-Clause |
| reportlab | 5.0.1 | BSD License |
| requests | 2.34.2 | Apache Software License |
| urllib3 | 2.8.0 | MIT |
| yarl | 1.25.1 | Apache-2.0 |

ReportLab is used for PDF generation. Package license declarations and exact wheel provenance are recorded in the SBOM; redistribution must retain applicable upstream license texts, copyright notices and bundled native-library notices, including Pillow third-party material. certifi declares MPL-2.0; review applicable source and notice obligations. This inventory is not a license-compliance certification. Full captured installed license texts for legal review are retained in the inspection evidence as `runtime-dependency-notices.evidence.md` and `runtime-licenses.deduplicated.json`; these are not substitutes for the notices required in an actual distributed artifact.

## Python and installer tooling

The inspection host used CPython 3.13.14 (Python Software Foundation License). The Docker base remains a mutable Python 3.13 tag; maintainers must record the actual shipped interpreter/base digest and OS/native-library license inventory before release. Installer pip is excluded from the application-runtime SBOM and must be inventoried/audited separately; exclusion is not a claim that a final image lacks it.

## Optional scanning and signing

axe-core 4.11.0 (MPL-2.0) and Playwright 1.63.0 are optional scanning/test components, not dependencies in this runtime inventory. Chromium and upstream scanner/native components require separate inventory and notices when distributed.

The legacy release requirements pin ReportLab 4.4.1, PyYAML 6.0.2 and Sigstore 4.4.0, but the inspected signing workflow does not consume that file and uses Python 3.12 with unpinned ReportLab/PyYAML. A separately audited Python 3.13 release-tool closure does not verify that signing environment. No signing-runtime readiness or complete signing-license claim is made here.

No third-party fonts, logos, customer data, or proprietary scanner exports are intentionally distributed. Release maintainers must review actual artifact dependency locks, image/OS/native inventory, fixtures and generated evidence, and preserve required license texts/notices before each release.
