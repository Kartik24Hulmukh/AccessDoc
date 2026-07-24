# Reproducibility

AccessDoc's core claim is that the same input produces a **byte-identical**
evidence bundle. If that is not true, the hash chain proves nothing, because a
verifier cannot distinguish tampering from normal variation.

## Three sources of non-determinism, all closed

| # | Source | Symptom | Fix |
|---|--------|---------|-----|
| 1 | ReportLab `/CreationDate`, `/ModDate`, two `/ID` md5s | PDF bytes differ every run | `reportlab.rl_config.invariant = 1`, set before any canvas is constructed |
| 2 | in-toto attestation timestamp read from the wall clock | Attestation differs between runs that straddle a second boundary | Timestamp derived from caller-supplied `audit_date` via `normalize_timestamp()` |
| 3 | `zipfile.writestr()` stamping each entry with the current time | Archive bytes differ even when every member is identical | Every entry written through a `ZipInfo` pinned to a fixed epoch, fixed mode, fixed `create_system` |

Source 3 is the one most projects miss. Members can each be byte-identical
while the containing archive still differs, because the local file headers
carry mtimes.

## How it is tested

A naive determinism test builds two bundles back to back and compares them.
**That test passes by luck.** If both runs complete inside the same wall-clock
second, a timestamp bug is invisible.

`tests/test_determinism.py` therefore sleeps across a second boundary between
runs:

```python
z1 = build_bundle(build_artifacts(BODY))
time.sleep(1.1)
z2 = build_bundle(build_artifacts(BODY))
assert z1 == z2
```

Any regression in any of the three sources above fails this test.

## Verifying it yourself

```bash
accessdoc bundle scan.json --audit-date 2026-07-25 --out a.zip
sleep 2
accessdoc bundle scan.json --audit-date 2026-07-25 --out b.zip
sha256sum a.zip b.zip   # identical
```

`audit_date` must be pinned. It is an input, not an observation.
