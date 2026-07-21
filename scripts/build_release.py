from __future__ import annotations
from pathlib import Path
import hashlib,json,stat,zipfile
root=Path(__file__).resolve().parents[1];outdir=root/'dist';outdir.mkdir(exist_ok=True);version=(root/'VERSION').read_text().strip();out=outdir/f'accessdoc-{version}-source.zip';excluded={'.git','dist','artifacts','__pycache__','.pytest_cache','.venv','node_modules'};files=[p for p in root.rglob('*') if p.is_file() and not any(x in p.parts for x in excluded) and p.suffix not in {'.pyc','.pid','.sqlite3'}]
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
 for p in sorted(files,key=lambda x:x.relative_to(root).as_posix()):
  rel=p.relative_to(root).as_posix();info=zipfile.ZipInfo(rel,(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=(0o100755 if p.stat().st_mode&stat.S_IXUSR else 0o100644)<<16;z.writestr(info,p.read_bytes(),compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
manifest={p.relative_to(root).as_posix():{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size} for p in sorted(files)};(outdir/'SOURCE-MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n');(outdir/'SHA256SUMS.txt').write_text(f'{hashlib.sha256(out.read_bytes()).hexdigest()}  {out.name}\n');print(out)
