"""Isolated synthetic Git fixtures: no repository edits or real credentials."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'build_source_bundle.py'
spec = importlib.util.spec_from_file_location('source_candidate_boundary', SCRIPT)
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


class SourceCandidateBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='source-candidate-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo'
        self.root.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Synthetic Fixture')
        self.git('config', 'user.email', 'synthetic@example.invalid')
        self.put('VERSION', '0.0.0-synthetic\n')
        self.put('.gitignore', '.env\ndist/\nignored-private/\n')
        self.put('README.md', 'Synthetic public source\n')
        self.put('.env.example', 'ACCESSDOC_API_KEY=\n')
        self.commit()

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True,
                              capture_output=True).stdout

    def put(self, name, text):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')
        return p

    def symlink(self, link, target, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError):
            self.skipTest('OS symlink creation unavailable; Git mode rejection tested separately')

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'synthetic fixture')

    def build(self):
        return packager.build_source_bundle(self.root)

    def refused(self):
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse((self.root / 'dist').exists())

    def test_ignored_untracked_and_generated_canaries_excluded(self):
        self.put('.env', 'SYNTHETIC_IGNORED_CANARY\n')
        self.put('ignored-private/notes.txt', 'SYNTHETIC_PRIVATE_CANARY\n')
        self.put('untracked-private.txt', 'SYNTHETIC_UNTRACKED_CANARY\n')
        self.put('build-output.json', 'SYNTHETIC_GENERATED_CANARY\n')
        with zipfile.ZipFile(self.build()) as z:
            self.assertEqual(set(z.namelist()), {'.env.example', '.gitignore', 'README.md', 'VERSION'})
            self.assertFalse(any(b'CANARY' in z.read(n) for n in z.namelist()))

    def test_tracked_private_generated_policy_public_example_preserved(self):
        for n in ['.env.production', '.vercel/project.json', 'private/notes.txt',
                  'secrets/key.txt', 'artifacts/result.json', 'trace.log']:
            self.put(n, 'SYNTHETIC_DENIED_CANARY\n')
        self.commit()
        with zipfile.ZipFile(self.build()) as z:
            self.assertIn('.env.example', z.namelist())
            self.assertFalse(any(b'CANARY' in z.read(n) for n in z.namelist()))

    def test_dirty_worktree_refused(self):
        self.put('README.md', 'changed\n')
        self.refused()

    def test_dirty_index_refused_even_if_worktree_restored(self):
        self.put('README.md', 'changed\n')
        self.git('add', 'README.md')
        self.put('README.md', 'Synthetic public source\n')
        self.refused()

    def test_staged_new_file_refused(self):
        self.put('new.txt', 'synthetic\n')
        self.git('add', 'new.txt')
        self.refused()

    def test_missing_git_metadata_refused(self):
        root = Path(self.temp.name) / 'no-git'
        root.mkdir()
        (root / 'VERSION').write_text('1\n')
        with self.assertRaises(ValueError):
            packager.build_source_bundle(root)
        self.assertFalse((root / 'dist').exists())

    def test_enclosing_repository_not_accepted(self):
        child = self.root / 'child'
        child.mkdir()
        with self.assertRaises(ValueError):
            packager.build_source_bundle(child)
        self.assertFalse((child / 'dist').exists())

    def test_unborn_head_refused(self):
        root = Path(self.temp.name) / 'unborn'
        root.mkdir()
        subprocess.run(['git', '-C', str(root), 'init', '-q'], check=True)
        with self.assertRaises(ValueError):
            packager.build_source_bundle(root)

    def test_tracked_symlink_to_external_canary_refused(self):
        outside = Path(self.temp.name) / 'external-private.txt'
        outside.write_text('SYNTHETIC_EXTERNAL_CANARY\n')
        self.symlink(self.root / 'tracked-link', outside)
        self.commit()
        self.refused()

    def test_symlink_even_in_excluded_directory_refused(self):
        outside = Path(self.temp.name) / 'external-private.txt'
        outside.write_text('SYNTHETIC_EXTERNAL_CANARY\n')
        (self.root / 'private').mkdir()
        self.symlink(self.root / 'private/link', outside)
        self.commit()
        self.refused()

    def test_gitlink_refused_without_submodule_checkout(self):
        head = self.git('rev-parse', 'HEAD').decode().strip()
        self.git('update-index', '--add', '--cacheinfo', f'160000,{head},submodule')
        self.git('commit', '-qm', 'synthetic gitlink')
        self.refused()

    def test_manifest_checksums_and_exact_provenance(self):
        archive = self.build()
        dist = archive.parent
        manifest = json.loads((dist / 'MANIFEST.json').read_text())
        provenance = json.loads((dist / 'SOURCE-PROVENANCE.json').read_text())
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(set(manifest), set(z.namelist()))
            for n in z.namelist():
                self.assertEqual(manifest[n], hashlib.sha256(z.read(n)).hexdigest())
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.assertEqual((dist / 'SHA256SUMS.txt').read_text(), f'{digest}  {archive.name}\n')
        self.assertEqual(provenance['source_commit'], self.git('rev-parse', 'HEAD').decode().strip())
        self.assertEqual(provenance['source_tree'], self.git('rev-parse', 'HEAD^{tree}').decode().strip())
        self.assertEqual(provenance['archive_sha256'], digest)
        self.assertEqual(provenance['manifest_sha256'], hashlib.sha256((dist / 'MANIFEST.json').read_bytes()).hexdigest())

    def test_reproducible_despite_worktree_mtime_and_outputs(self):
        executable = self.put('run.sh', '#!/bin/sh\nexit 0\n')
        executable.chmod(0o755)
        # Windows ignores chmod for Git mode. Establish the committed mode
        # explicitly, with filemode=false also exercising that path on Linux.
        self.git('config', 'core.filemode', 'false')
        self.git('add', 'run.sh')
        self.git('update-index', '--chmod=+x', 'run.sh')
        self.commit()
        archive = self.build()
        before = {p.name: p.read_bytes() for p in archive.parent.iterdir()}
        os.utime(self.root / 'README.md', (1700000000, 1700000000))
        self.put('untracked.txt', 'synthetic ignored by source boundary\n')
        self.build()
        self.assertEqual(before, {p.name: p.read_bytes() for p in archive.parent.iterdir()})
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(z.getinfo('run.sh').external_attr >> 16, 0o100755)
            self.assertTrue(all(i.date_time == (1980, 1, 1, 0, 0, 0) for i in z.infolist()))

    def test_hidden_worktree_skip_flag_refused(self):
        self.git('update-index', '--skip-worktree', 'README.md')
        self.put('README.md', 'SYNTHETIC_WORKTREE_ONLY_CANARY\n')
        self.refused()

    def test_hidden_assume_unchanged_flag_refused(self):
        self.git('update-index', '--assume-unchanged', 'README.md')
        self.put('README.md', 'SYNTHETIC_WORKTREE_ONLY_CANARY\n')
        self.refused()

    def test_git_symlink_mode_refused_without_os_symlink_support(self):
        # core.symlinks=false gives a clean regular-file representation on any OS.
        self.git('config', 'core.symlinks', 'false')
        self.put('link-representation', '../SYNTHETIC_PRIVATE_TARGET\n')
        self.git('add', 'link-representation')
        oid = self.git('rev-parse', ':link-representation').decode().strip()
        self.git('update-index', '--cacheinfo', f'120000,{oid},link-representation')
        self.git('commit', '-qm', 'synthetic symlink tree mode')
        self.refused()

    def test_invalid_version_refused(self):
        self.put('VERSION', '../../private\n')
        self.commit()
        self.refused()

    def test_missing_committed_version_refused(self):
        self.git('rm', 'VERSION')
        self.git('commit', '-qm', 'remove synthetic version')
        self.refused()

    def test_dist_symlink_refused(self):
        outside = Path(self.temp.name) / 'external-output'
        outside.mkdir()
        self.symlink(self.root / 'dist', outside, directory=True)
        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual(list(outside.iterdir()), [])

    def test_artifact_destination_symlink_refused(self):
        (self.root / 'dist').mkdir()
        outside = Path(self.temp.name) / 'private-output'
        outside.write_text('SYNTHETIC_KEEP\n')
        self.symlink(self.root / 'dist/MANIFEST.json', outside)
        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual(outside.read_text(), 'SYNTHETIC_KEEP\n')


if __name__ == '__main__':
    unittest.main()
