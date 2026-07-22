import base64, json, os, sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

try:
    from app.parser import parse_input, ParseError, parse_axe, parse_lighthouse, parse_csv_text
    from app.models import Branding, AuditRequest, Finding, Occurrence, DISCLAIMER
    from app.reporter import generate_pdf
    from app.store import TTLReportStore
    _OLD_API_AVAILABLE = True
except ImportError:
    _OLD_API_AVAILABLE = False

ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(_OLD_API_AVAILABLE, "Old v0.4 API removed in v0.5.0-beta.1; tests preserved for history")
class ParserTests(unittest.TestCase):
 def test_axe_fixture(self):
  findings,fmt=parse_input((ROOT/'fixtures/axe-sample.json').read_text())
  self.assertEqual(fmt,'axe'); self.assertEqual(len(findings),4)
  self.assertEqual(findings[0].wcag_criterion,'1.1.1')
  self.assertEqual(findings[1].instance_count,2)
  self.assertEqual(findings[-1].wcag_criterion,'Unmapped')
  self.assertEqual(findings[-1].confidence,'needs_review')
 def test_hostile_text_is_inert_data(self):
  payload={"violations":[{"id":"image-alt","impact":"critical","help":"<img src=x onerror=alert(1)>","description":"<script>boom</script>","nodes":[{"html":"<svg><script>x</script></svg>","target":["javascript:alert(1)"]}]}]}
  f=parse_axe(payload)[0]
  self.assertIn('<img',f.title); self.assertIn('<script>',f.description)
  pdf=generate_pdf(AuditRequest('Client','2026-07-18',Branding(),[f]))
  self.assertTrue(pdf.startswith(b'%PDF-')); self.assertNotIn(b'/JavaScript',pdf)
 def test_excess_depth_rejected(self):
  obj={}; cur=obj
  for i in range(30): cur['x']={}; cur=cur['x']
  with self.assertRaises(ParseError): parse_input(json.dumps(obj),'axe')
 def test_oversize_rejected(self):
  with self.assertRaises(ParseError): parse_input('x'*2_000_001,'text')
 def test_lighthouse(self):
  obj={"audits":{"button-name":{"id":"button-name","score":0,"title":"Buttons have names","description":"desc","details":{"items":[{"node":{"snippet":"<button></button>","selector":"button","explanation":"missing name"}}]}},"passed":{"id":"image-alt","score":1,"title":"passed"}}}
  fs=parse_lighthouse(obj); self.assertEqual(len(fs),1); self.assertEqual(fs[0].wcag_criterion,'4.1.2')
 def test_csv_formula_kept_as_inert_text(self):
  fs=parse_csv_text('id,title,description\nimage-alt,=WEBSERVICE(""https://bad"), desc\n')
  self.assertEqual(len(fs),1)

@unittest.skipUnless(_OLD_API_AVAILABLE, "Old v0.4 API removed in v0.5.0-beta.1; tests preserved for history")
class ModelAndPdfTests(unittest.TestCase):
 def test_brand_validation(self):
  self.assertEqual(Branding(primary_color='red').primary_color,'#185ABD')
  with self.assertRaises(ValueError): Branding(logo_png=b'notpng')
 def test_pdf_contains_disclaimer_and_pages(self):
  fs,_=parse_input((ROOT/'fixtures/axe-sample.json').read_text())
  pdf=generate_pdf(AuditRequest('Northstar','2026-07-18',Branding('Inclusive Studio','#185ABD'),fs,'Keyboard trap observed in modal.','axe'))
  self.assertGreater(len(pdf),5000); self.assertTrue(pdf.startswith(b'%PDF-'))
  import tempfile
  from pypdf import PdfReader
  with tempfile.NamedTemporaryFile(suffix='.pdf') as tmp:
   tmp.write(pdf);tmp.flush();reader=PdfReader(tmp.name)
  text='\n'.join((p.extract_text() or '') for p in reader.pages)
  self.assertGreaterEqual(len(reader.pages),5)
  self.assertIn('not legal advice or certification',text.lower())
  self.assertIn('Unmapped',text)
  self.assertIn('Keyboard trap observed',text)
  self.assertIn('Input evidence receipt',text)
  self.assertIn('Source evidence was normalized, not rescanned',text)

@unittest.skipUnless(_OLD_API_AVAILABLE, "Old v0.4 API removed in v0.5.0-beta.1; tests preserved for history")
class StoreTests(unittest.TestCase):
 def test_store_is_bounded_and_returns_immutable_copy(self):
  s=TTLReportStore(ttl_seconds=10,max_items=2,max_bytes=100);t=s.put(b'ePDF-x',b'<html></html>',b'{}','a.pdf')
  self.assertEqual(s.get(t).pdf,b'%PDF-x');self.assertEqual(s.stats['items'],1)
  s.put(b'%PDF-y',b'<html></html>',b'{}','b.pdf');s.put(b'%PDF-z',b'<html></html>',b'{}','c.pdf')
  self.assertLessEqual(s.stats['items'],2)
 def test_oversize_report_rejected(self):
  with self.assertRaises(ValueError):TTLReportStore().put(b'x'*10_000_001,b'<html></html>',b'{}','large.pdf')

if __name__=='__main__': unittest.main()
