"""Package reviewed HEAD blobs, never the working tree or symlink targets.

Filename exclusions are defense in depth, not a secret-free certification.
The tracked .env.example is intentionally public configuration documentation.
"""
from pathlib import Path, PurePosixPath
import hashlib
import json
import re
import subprocess
import tempfile
import zipfile


EXCLUDED_DIRS = {
    '.git', '.vercel', '.venv', 'node_modules', 'dist', 'artifacts',
    '__pycache__', '.pytest_cache', 'private', 'secrets',
}
EXCLUDED_SUFFIXES = {'.pyc', '.pyo', '.pid', '.sqlite3', '.log'}


def git(root, *args):
    result = subprocess.run(
        ['git', '--no-replace-objects', '-C', str(root), *args], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        raise ValueError('Required Git source metadata or clean-state check failed')
    return result.stdout


def require_clean(root, commit):
    if git(root, 'rev-parse', 'HEAD').decode().strip() != commit:
        raise ValueError('HEAD changed during source packaging')
    # These index flags hide worktree differences from ordinary status checks.
    for entry in git(root, 'ls-files', '-v', '-z').split(b'\0'):
        if entry and (entry[:1] == b'S' or entry[:1].islower()):
            raise ValueError('Hidden tracked-file state flags are not supported')
    if git(root, 'status', '--porcelain=v1', '--untracked-files=no'):
        raise ValueError('Tracked working tree and index must be clean')


def excluded(name):
    path = PurePosixPath(name)
    return (
        bool(EXCLUDED_DIRS.intersection(path.parts))
        or path.suffix in EXCLUDED_SUFFIXES
        or (path.name.startswith('.env') and path.name != '.env.example')
    )


def build_source_bundle(root):
    root = Path(root).resolve()
    # Do not silently use metadata from an enclosing repository.
    top = Path(git(root, 'rev-parse', '--show-toplevel').decode().strip()).resolve()
    if top != root:
        raise ValueError('Source root must be the Git repository root')
    commit = git(root, 'rev-parse', '--verify', 'HEAD^{commit}').decode().strip()
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('A complete forty-character source commit is required')
    require_clean(root, commit)
    tree = git(root, 'rev-parse', commit + '^{tree}').decode().strip()
    files = {}
    modes = {}
    for record in git(root, 'ls-tree', '-rz', '--full-tree', commit).split(b'\0'):
        if not record:
            continue
        metadata, raw_name = record.split(b'\t', 1)
        mode, kind, oid = metadata.decode('ascii').split()
        # Reject links and gitlinks even in excluded paths; never follow them.
        if mode not in ('100644', '100755') or kind != 'blob':
            raise ValueError('Unsupported Git tree mode; links and submodules forbidden')
        name = raw_name.decode('utf-8', errors='strict')
        path = PurePosixPath(name)
        if (path.is_absolute() or any(part in ('', '.', '..') for part in name.split('/'))
                or '\\' in name or any(ord(c) < 32 or ord(c) == 127 for c in name)):
            raise ValueError('Unsafe source archive path')
        if excluded(name):
            continue
        files[name] = git(root, 'cat-file', 'blob', oid)
        modes[name] = mode
    if 'VERSION' not in files:
        raise ValueError('Committed VERSION is required')
    version = files['VERSION'].decode('utf-8').strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,127}', version):
        raise ValueError('Committed VERSION is not a safe artifact name')
    require_clean(root, commit)
    dist = root / 'dist'
    if dist.is_symlink() or (dist.exists() and not dist.is_dir()):
        raise ValueError('dist must be a real directory')
    name = f'accessdoc-{version}-source.zip'
    names = (name, 'MANIFEST.json', 'SHA256SUMS.txt', 'SOURCE-PROVENANCE.json')
    if any((dist / n).is_symlink() or (dist / n).is_dir() for n in names):
        raise ValueError('Artifact destinations must not be links or directories')
    dist.mkdir(exist_ok=True)
    # Validate and prepare everything before replacing the existing artifacts.
    with tempfile.TemporaryDirectory(prefix='source-candidate-', dir=dist) as td:
        stage = Path(td)
        archive = stage / name
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
            for filename in sorted(files):
                info = zipfile.ZipInfo(filename, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o100755 if modes[filename] == '100755' else 0o100644) << 16
                z.writestr(info, files[filename])
        manifest = {n: hashlib.sha256(files[n]).hexdigest() for n in sorted(files)}
        manifest_bytes = (json.dumps(manifest, indent=2) + '\n').encode()
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        (stage / 'MANIFEST.json').write_bytes(manifest_bytes)
        (stage / 'SHA256SUMS.txt').write_text(f'{digest}  {name}\n', encoding='utf-8')
        provenance = {
            'schema_version': 1, 'source_commit': commit, 'source_tree': tree,
            'source_boundary': 'clean Git HEAD regular-file blobs only',
            'archive': name, 'archive_sha256': digest,
            'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
            'file_count': len(files),
            'exclusion_policy': {
                'directories': sorted(EXCLUDED_DIRS),
                'suffixes': sorted(EXCLUDED_SUFFIXES),
                'environment_files': '.env* excluded except tracked .env.example',
            },
            'limitations': 'Filename policy and hashes do not establish secret freedom, origin or human approval.',
        }
        (stage / 'SOURCE-PROVENANCE.json').write_text(
            json.dumps(provenance, indent=2) + '\n', encoding='utf-8')
        require_clean(root, commit)
        for n in names:
            (stage / n).replace(dist / n)
    return dist / name


def main():
    try:
        print(build_source_bundle(Path(__file__).resolve().parents[1]))
    except (ValueError, OSError, UnicodeError) as exc:
        raise SystemExit(f'Source packaging refused: {exc}') from None


if __name__ == '__main__':
    main()
