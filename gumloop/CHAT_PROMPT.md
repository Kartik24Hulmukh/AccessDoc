# Gumloop Chat Prompt - Ship AccessDoc v0.6.0-beta.1

Attached: `accessdoc-v0.6.0-beta1.zip`. Overlay it onto
`Kartik24Hulmukh/AccessDoc` (current base = v0.5.0-beta.1), verify, and ship to
`main`. Work autonomously; if a step is blocked, note it and keep going.

## Step 1 - Prepare
1. Clone `Kartik24Hulmukh/AccessDoc` (branch `main`).
2. Create working branch `release/v0.6.0-beta.1`.
3. Extract the ZIP and copy its contents over the repo root, overwriting
   same-path files and adding new ones.

## Step 2 - File map (what the ZIP changes)
**New in v0.6:** `app/sarif.py`, `app/vpat.py`, `app/eaa.py`, `app/manual.py`,
`app/enrich.py`, `app/timeseries.py`, `app/catalog.py`, `app/scan.py`,
`app/intoto.py`, `app/bundle.py`, `cli.py`, `mcp/__init__.py`, `mcp/server.py`,
`scripts/ci_gate.py`, `scripts/stress_test.py`, `action.yml`, `SKILL.md`,
`ACCESSIBILITY.md`, and tests `test_security/sarif/manual/eaa/vpat/enrich/timeseries`.
**Hardened (replace):** `app/reporter.py` (HTML escaping), `app/openacr.py`
(YAML escaping), `app/service.py`, `app/models.py`, `app/parser.py`,
`api/handler.py`, `VERSION` (-> `0.6.0-beta.1`), `requirements.txt`, `README.md`,
`tests/test_cli.py`, `tests/test_mcp.py`.

## Step 3 - Verify (MUST pass before pushing to main)
```bash
pip install reportlab PyYAML
python3 -m unittest discover -s tests -p 'test_*.py'   # expect OK, 63 tests
python3 scripts/stress_test.py                          # expect 12/12 checks passed
python3 cli.py catalog                                  # sanity print
```
If either suite fails: DO NOT push to main. Open a PR from
`release/v0.6.0-beta.1` with the full log and stop.

## Step 4 - Ship
1. Commit: `release: AccessDoc v0.6.0-beta.1 (security hardening + SARIF/VPAT/EAA/MCP/CLI)`.
2. If tests pass, merge into `main` (or push per repo convention).
3. Try to create tag `v0.6.0-beta.1`; if unavailable, push a branch ref and note it.

## Step 5 - Deploy & confirm
1. Trigger a Vercel production deploy of `access-doc` (team `atlas16`).
2. Keep `ssoProtection: null`.
3. Confirm `curl -s https://access-doc.vercel.app/` returns
   `{"service":"AccessDoc","adapter_version":"0.6.0-beta.1","status":"ok"}`.

## Step 6 - Owner-only checklist (report, don't block)
- [ ] If workflow push 403'd, add `.github/workflows/accessdoc.yml` via GitHub UI
      (calls root `action.yml`).
- [ ] Confirm annotated tag `v0.6.0-beta.1` if only a branch ref was pushed.
- [ ] Naming/trademark check before public launch (`accessdoc.fr` collision).
- [ ] Adoption gate before broad launch: >=5 practitioners, >=2 who would
      "hand the output to a client".

## Final report
Return: commit SHA, test results (63 + 12/12), the live health JSON, and the
remaining owner-only checklist items.
