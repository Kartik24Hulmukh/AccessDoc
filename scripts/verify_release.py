from __future__ import annotations
import json,os,re,subprocess,sys,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1];checks={}
def add(name,ok,detail=''):
 checks[name]={'status':'PASS' if ok else 'FAIL','detail':detail};return ok
def run(name,cmd):
 env={**os.environ,'PYTHONPYCACHEPREFIX':tempfile.mkdtemp(prefix='accessdoc-pycache-')};p=subprocess.run(cmd,cwd=root,text=True,capture_output=True,env=env);checks[name]={'status':'PASS' if p.returncode==0 else 'FAIL','exitCode':p.returncode,'stdout':p.stdout[-3000:],'stderr':p.stderr[-3000:]};return p.returncode==0
ok=run('compile',[sys.executable,'-m','compileall','-q','app','api','tests'])
ok=run('tests',[sys.executable,'-W','error::ResourceWarning','-m','unittest','discover','-s','tests','-v']) and ok
files=[p for p in root.rglob('*') if p.is_file() and not any(x in p.parts for x in {'.git','dist','artifacts','__pycache__','.venv','node_modules'}) and p.name!='verify_release.py' and p.stat().st_size<3_000_000]
def hits(pattern,paths,flags=re.I):
 rx=re.compile(pattern,flags);out=[]
 for p in paths:
  for n,line in enumerate(p.read_text(errors='ignore').splitlines(),1):
   if rx.search(line):out.append(f'{p.relative_to(root)}:{n}')
 return out
secret=hits(r'sk_live_|AKIA[0-9A-Z]{16}|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY',files);ok=add('secret_patterns',not secret,secret) and ok
public=[root/x for x in ['README.md','public/index.html','public/static/app.js','CHANGELOG.md','COMPLETION_STATUS.md','FINAL_HANDOFF.md','STATE.md'] if (root/x).is_file()]
banned=hits(r'100x|revolutionary|game-changing|guaranteed|production-ready|production-capable|WCAG compliant|PDF/UA compliant|cryptographic proof',public);ok=add('claims',not banned,banned) and ok
placeholder=hits(r'REPLACE|TODO|example\.org|ACCOUNT_ID',files,0);ok=add('placeholders',not placeholder,placeholder) and ok
stale=[str(p.relative_to(root)) for p in root.rglob('*') if (p.is_file() and p.suffix in {'.pyc','.pid','.sqlite3'}) or (p.is_dir() and p.name=='__pycache__')];ok=add('stale_files',not stale,stale) and ok
workflows=list((root/'.github/workflows').glob('*.y*ml'));mutable=hits(r'uses:\s+[^./][^@\s]+@(main|master|v?\d+(?:\.\d+){0,2})\s*$',workflows);ok=add('immutable_action_refs',not mutable,mutable) and ok
priv=[]
for p in workflows:
 txt=p.read_text();
 if re.search(r'contents:\s*write|packages:\s*write|deployments:\s*write|id-token:\s*write|pull_request_target|gh release|create-release',txt,re.I):priv.append(str(p.relative_to(root)))
ok=add('non_publishing_workflows',not priv,priv) and ok
required=['VERSION','LICENSE','SECURITY.md','CONTRIBUTING.md','CODE_OF_CONDUCT.md','docs/CLAIMS_POLICY.md','docs/PRIVACY.md','docs/EVALUATION_PROTOCOL.md','docs/RELEASE_GATES.md','docs/RECEIPT_FORMAT.md','docs/GITHUB_PUBLICATION_CHECKLIST.md','docs/100X_ROADMAP.md','scripts/verify_receipt.py','tests/test_html_companion.py','scripts/accessibility_e2e.js','scripts/stress_test.py','scripts/build_release.py','docs/LOCAL_STRESS_TESTING.md','gumloop/SYSTEM_PROMPT.md','gumloop/CHAT_PROMPT.md','Dockerfile','.github/ISSUE_TEMPLATE/accessibility.yml','api/bundle.py','app/bundle.py','public/index.html','vercel.json','.python-version','docs/VERCEL_DEPLOYMENT.md','scripts/verify_bundle.py'];missing=[x for x in required if not (root/x).is_file()];ok=add('required_files',not missing,missing) and ok
version=(root/'VERSION').read_text().strip();surfaces=[root/'app/main.py',root/'app/models.py',root/'pyproject.toml',root/'tests/test_http.py',root/'api/bundle.py'];bad=[str(p.relative_to(root)) for p in surfaces if version not in p.read_text()];ok=add('version_consistency',not bad,bad) and ok
print(json.dumps(checks,indent=2));raise SystemExit(0 if ok else 1)
