from __future__ import annotations
from hashlib import sha256
from io import BytesIO
import json, stat, zipfile
from .service import Artifacts, MAX_BUNDLE_BYTES, VERSION, build_artifacts

MEMBERS=('report.pdf','report.html','receipt.json','manifest.json')
FIXED_TIME=(2020,1,1,0,0,0)
MEDIA={'report.pdf':'application/pdf','report.html':'text/html; charset=utf-8','receipt.json':'application/json'}

class BundleTooLarge(ValueError):pass

def _member(name:str,data:bytes)->zipfile.ZipInfo:
    info=zipfile.ZipInfo(name,FIXED_TIME)
    info.compress_type=zipfile.ZIP_DEFLATED
    info.create_system=3
    info.external_attr=(stat.S_IFREG|0o644)<<16
    info.flag_bits|=0x800
    return info

def build_bundle(artifacts:Artifacts)->bytes:
    payloads={'report.pdf':artifacts.pdf,'report.html':artifacts.html,'receipt.json':artifacts.receipt_bytes}
    manifest={'schema_version':'1.0','bundle_type':'accessdoc-report','generator_version':VERSION,'files':[{'path':name,'media_type':MEDIA[name],'bytes':len(payloads[name]),'sha256':sha256(payloads[name]).hexdigest()} for name in ('report.pdf','report.html','receipt.json')]}
    payloads['manifest.json']=(json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
    out=BytesIO()
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name in MEMBERS:z.writestr(_member(name,payloads[name]),payloads[name])
    data=out.getvalue()
    if len(data)>MAX_BUNDLE_BYTES:raise BundleTooLarge('Generated report bundle exceeds the 4 MB response limit')
    validate_bundle(data)
    return data

def validate_bundle(data:bytes)->dict:
    if not data.startswith(b'PK') or len(data)>MAX_BUNDLE_BYTES:raise ValueError('Bundle integrity check failed')
    with zipfile.ZipFile(BytesIO(data)) as z:
        infos=z.infolist();names=[x.filename for x in infos]
        if tuple(names)!=MEMBERS or len(names)!=len(set(names)) or z.testzip() is not None:raise ValueError('Bundle member validation failed')
        for info in infos:
            if info.is_dir() or info.filename.startswith('/') or '..' in info.filename.split('/') or '\\' in info.filename:raise ValueError('Unsafe bundle member')
        manifest=json.loads(z.read('manifest.json'))
        if [x['path'] for x in manifest['files']]!=list(MEMBERS[:-1]):raise ValueError('Manifest member validation failed')
        for item in manifest['files']:
            member=z.read(item['path'])
            if item['bytes']!=len(member) or item['sha256']!=sha256(member).hexdigest():raise ValueError('Manifest digest validation failed')
        if not z.read('report.pdf').startswith(b'%PDF-'):raise ValueError('PDF integrity check failed')
        return manifest

def generate_bundle(body:dict)->tuple[bytes,dict]:
    artifacts=build_artifacts(body)
    return build_bundle(artifacts),artifacts.summary
