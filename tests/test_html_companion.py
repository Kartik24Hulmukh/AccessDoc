import hashlib,re,unittest

try:
    from app.html_report import generate_html,fragment_id
    from app.models import AuditRequest,Branding,Finding,Occurrence
    _OLD_API_AVAILABLE = True
except ImportError:
    _OLD_API_AVAILABLE = False

@unittest.skipUnless(_OLD_API_AVAILABLE, "Old v0.4 API removed in v0.5.0-beta.1; tests preserved for history")
class HtmlCompanionTests(unittest.TestCase):
 def finding(self,fid='A 1',rule='custom/<script>'):
  return Finding(fid,'axe',rule,'<script>alert(1)</script>','desc','Unmapped','',' N/A','needs-review','Unknown','impact','fix',[Occurrence(failure_summary='<img src=x onerror=alert(1)>')])
 def test_fragments_are_stable_safe_and_unique(self):
  a=self.finding('one','duplicate');b=self.finding('two','duplicate');self.assertEqual(fragment_id(a),fragment_id(a));self.assertNotEqual(fragment_id(a),fragment_id(b));self.assertRegex(fragment_id(a),r'^finding-[a-z0-9-]+-[0-9a-f]{12}$')
 def test_hostile_content_is_inert(self):
  f=self.finding();req=AuditRequest('Client','2026-07-21',Branding(),[f]);receipt={'submitted_text_sha256':'a'*64,'pdf_sha256':'b'*64}
  html=generate_html(req,receipt).decode();self.assertNotIn('<script>alert',html);self.assertNotIn('<img src=x',html);self.assertIn('&lt;script&gt;',html);ids=re.findall(r'id="([^"]+)"',html);self.assertEqual(len(ids),len(set(ids)))
if __name__=='__main__':unittest.main()
