from __future__ import annotations
import hashlib
from typing import Any

REQUIRED_FIELDS={
    'source_filename','submitted_text_sha256','detected_format','generator_version',
    'catalog_version','mapped_findings','unmapped_findings','manual_findings_included',
    'pdf_sha256','scope_statement'
}

def verify_receipt(receipt:dict[str,Any], submitted_text:bytes, pdf:bytes)->list[str]:
    errors=[]
    missing=sorted(REQUIRED_FIELDS-set(receipt))
    if missing:errors.append('missing fields: '+', '.join(missing))
    expected_input=hashlib.sha256(submitted_text).hexdigest()
    if receipt.get('submitted_text_sha256')!=expected_input:errors.append('submitted text SHA-256 mismatch')
    expected_pdf=hashlib.sha256(pdf).hexdigest()
    if receipt.get('pdf_sha256')!=expected_pdf:errors.append('PDF SHA-256 mismatch')
    if 'did not rescan' not in str(receipt.get('scope_statement','')):errors.append('scope statement missing no-rescan boundary')
    for key in ('mapped_findings','unmapped_findings'):
        if not isinstance(receipt.get(key),int) or receipt.get(key,0)<0:errors.append(f'{key} must be a non-negative integer')
    if not isinstance(receipt.get('manual_findings_included'),bool):errors.append('manual_findings_included must be boolean')
    return errors
