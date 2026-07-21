import hashlib,unittest
from app.receipt import verify_receipt

class ReceiptVerifierTests(unittest.TestCase):
 def make(self,source=b'{"test":true}\n',pdf=b'%PDF-test'):
  return {'source_filename':'sample.json','submitted_text_sha256':hashlib.sha256(source).hexdigest(),'detected_format':'axe','generator_version':'0.4.0-beta.4','catalog_version':'wcag-2.2-accessdoc-2026-01','mapped_findings':3,'unmapped_findings':1,'manual_findings_included':False,'pdf_sha256':hashlib.sha256(pdf).hexdigest(),'scope_statement':'Digest identifies submitted UTF-8 input text; AccessDoc normalized supplied evidence and did not rescan or authenticate its source.'}
 def test_matching_files_pass(self):
  source=b'{"test":true}\n';pdf=b'%PDF-test';self.assertEqual(verify_receipt(self.make(source,pdf),source,pdf),[])
 def test_tampering_fails(self):
  source=b'{"test":true}\n';pdf=b'%PDF-test';errors=verify_receipt(self.make(source,pdf),source+b'x',pdf+b'x');self.assertIn('submitted text SHA-256 mismatch',errors);self.assertIn('PDF SHA-256 mismatch',errors)
if __name__=='__main__':unittest.main()
