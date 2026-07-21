import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class OssReleaseTests(unittest.TestCase):
 def test_commerce_runtime_is_absent(self):
  forbidden=['str'+'ipe','ACCESSDOC_'+'PAYMENT','BILLING_'+'DB','payment-'+'success','checkout.'+'session']
  targets=[ROOT/'app',ROOT/'requirements.txt',ROOT/'.env.example',ROOT/'Dockerfile',ROOT/'docker-compose.yml',ROOT/'render.yaml',ROOT/'fly.toml',ROOT/'railway.json']
  hits=[]
  for target in targets:
   files=target.rglob('*') if target.is_dir() else [target]
   for p in files:
    if p.is_file() and p.suffix!='.pyc':
     text=p.read_text(errors='ignore').lower()
     for term in forbidden:
      if term.lower() in text:hits.append(f'{p.relative_to(ROOT)}:{term}')
  self.assertEqual(hits,[])
 def test_community_health_files_exist(self):
  required=['LICENSE','README.md','CONTRIBUTING.md','CODE_OF_CONDUCT.md','SECURITY.md','SUPPORT.md','GOVERNANCE.md','MAINTAINERS.md','CHANGELOG.md','CITATION.cff','RELEASE_CHECKLIST.md']
  self.assertEqual([x for x in required if not (ROOT/x).is_file()],[])
if __name__=='__main__':unittest.main()
