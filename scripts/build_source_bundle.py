from pathlib import Path
import hashlib,json,zipfile
root=Path(__file__).resolve().parents[1];dist=root/'dist';dist.mkdir(exist_ok=True)
version=(root/'VERSION').read_text().strip();name=f'accessdoc-{version}-source.zip';out=dist/name
exclude={'.git','dist','artifacts','__pycache__','.pytest_cache','.venv','node_modules'}
files=[p for p in root.rglob('*') if p.is_file() and not any(x in p.parts for x in exclude) and p.suffix not in {'.pyc','.pid','.sqlite3'}]
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
 for p in sorted(files):z.write(p,p.relative_to(root).as_posix())
manifest={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
(dist/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
(dist/'SHA256SUMS.txt').write_text(f'{hashlib.sha256(out.read_bytes()).hexdigest()}  {name}\n')
print(out)
