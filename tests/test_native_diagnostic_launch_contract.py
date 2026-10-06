"""Launch-control unit contracts, not actual native timing acceptance."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_launch_control', ROOT / 'scripts/run_one_native_diagnostic.py')
launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launch)

class NativeDiagnosticLaunchContracts(unittest.TestCase):
    def test_environment_does_not_forward_credentials_or_browser_access(self):
        with patch.dict(os.environ, {'PATH':'synthetic-path', 'MELIOUS_API_KEY':'not-forwarded',
                'GITHUB_TOKEN':'not-forwarded', 'AGENT_BROWSER_CDP':'not-forwarded',
                'OTEL_EXPORTER_OTLP_ENDPOINT':'not-forwarded'}, clear=True):
            env = launch.clean_environment(ROOT, Path('/synthetic-home'))
        for key in ('MELIOUS_API_KEY','GITHUB_TOKEN','AGENT_BROWSER_CDP','OTEL_EXPORTER_OTLP_ENDPOINT'):
            self.assertNotIn(key, env)
        self.assertEqual(env['PYTHONPATH'], str(ROOT))
        self.assertEqual(env['PYTHONDONTWRITEBYTECODE'], '1')
    def _committed_frozen_bytes(self):
        # Read immutable Git objects, not autocrlf-translated working-tree text.
        commit = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=10).decode('ascii').strip()
        committed = {}
        for name, digest in launch.EXPECTED.items():
            data = subprocess.check_output(
                ['git', 'show', f'{commit}:{name}'], cwd=ROOT, timeout=10)
            self.assertEqual(hashlib.sha256(data).hexdigest(), digest, name)
            committed[name] = data
        return committed

    def test_source_guards_match_the_frozen_inputs(self):
        committed = self._committed_frozen_bytes()
        with tempfile.TemporaryDirectory() as raw:
            canonical = Path(raw)
            for name, data in committed.items():
                target = canonical / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            self.assertEqual(launch.verify_sources(canonical), launch.EXPECTED)
        if os.name == 'nt':
            # Windows checkout may translate LF, but executable byte guards must
            # not normalize it. Reject anything beyond the exact Git/autocrlf forms.
            translated = False
            for name, data in committed.items():
                checkout = (ROOT / name).read_bytes()
                self.assertIn(checkout, (data, data.replace(b'\n', b'\r\n')), name)
                translated |= checkout != data
            if translated:
                with self.assertRaisesRegex(ValueError, 'no experiment admitted'):
                    launch.verify_sources(ROOT)
            else:
                self.assertEqual(launch.verify_sources(ROOT), launch.EXPECTED)
        else:
            self.assertEqual(launch.verify_sources(ROOT), launch.EXPECTED)

    def test_crlf_executable_bytes_are_rejected_without_normalization(self):
        committed = self._committed_frozen_bytes()
        with tempfile.TemporaryDirectory() as raw:
            checkout = Path(raw)
            staged_expected = {}
            for name, data in committed.items():
                self.assertNotIn(b'\r\n', data, name)
                self.assertIn(b'\n', data, name)
                target = checkout / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data.replace(b'\n', b'\r\n'))
                staged_expected[target] = launch.EXPECTED[name]
            with self.assertRaisesRegex(ValueError, 'no experiment admitted'):
                launch.verify_sources(checkout)
            with self.assertRaisesRegex(ValueError, 'staged'):
                launch.verify_staged(staged_expected)
            for name, data in committed.items():
                (checkout / name).write_bytes(data)
            self.assertEqual(launch.verify_sources(checkout), launch.EXPECTED)
            self.assertEqual(launch.verify_staged(staged_expected),
                             {str(path): digest for path, digest in staged_expected.items()})
    def test_changed_source_is_not_admitted(self):
        with patch.object(launch, 'EXPECTED', {'diagnostics/native-modern-probe/harness.py':'wrong'}):
            with self.assertRaisesRegex(ValueError, 'no experiment admitted'):
                launch.verify_sources(ROOT)
    def test_evidence_marks_oversize_instead_of_silent_success(self):
        if os.name != 'posix':
            with self.assertRaisesRegex(ValueError, 'requires POSIX'):
                launch.evidence_bytes(Path('/synthetic'))
            return
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / 'small.json').write_text('{}', encoding='utf-8')
            (root / 'large.log').write_bytes(b'x' * 17)
            with patch.object(launch, 'MAX_LOG_BYTES', 16):
                data, manifest = launch.evidence_bytes(root)
            self.assertEqual(len(manifest['omitted']), 1)
            self.assertEqual(manifest['omitted'][0]['name'], 'large.log')
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self.assertEqual(archive.read('small.json'), b'{}')
                self.assertEqual(json.loads(archive.read('bounded-evidence-manifest.json'))['acceptance_verdict'], 'none')
    def test_watchdog_kills_only_the_mocked_owned_group_and_preserves_failure(self):
        # Mocked control flow; does not claim a measured Darwin watchdog bound.
        process = Mock(pid=424242, returncode=-9)
        process.wait.side_effect = [subprocess.TimeoutExpired(['synthetic'], launch.WALL_SECONDS), -9]
        with tempfile.TemporaryDirectory() as raw, patch.object(launch.subprocess, 'Popen', return_value=process) as start, patch.object(launch, 'settle_owned_group', return_value=True) as settle:
            receipt = launch.run_one('synthetic', ['synthetic'], {}, Path(raw) / 'result')
            settle.assert_called_once_with(process)
            self.assertTrue(start.call_args.kwargs['start_new_session'])
            self.assertTrue(receipt['failed'])
            self.assertTrue(receipt['watchdog_expired'])
            self.assertEqual(receipt['child_exit'], -9)
            self.assertEqual(receipt['acceptance_verdict'], 'none')
    def test_normal_exit_also_settles_owned_descendants(self):
        process = Mock(pid=424242, returncode=0)
        with tempfile.TemporaryDirectory() as raw, patch.object(launch.subprocess, 'Popen', return_value=process), patch.object(launch, 'settle_owned_group', return_value=True) as settle:
            receipt = launch.run_one('synthetic', ['synthetic'], {}, Path(raw) / 'result')
        settle.assert_called_once_with(process)
        self.assertTrue(receipt['group_settled'])
    def test_post_launch_exception_still_settles_group(self):
        process = Mock(pid=424242, returncode=None)
        process.wait.side_effect = RuntimeError('synthetic wait error')
        with tempfile.TemporaryDirectory() as raw, patch.object(launch.subprocess, 'Popen', return_value=process), patch.object(launch, 'settle_owned_group', return_value=False) as settle:
            receipt = launch.run_one('synthetic', ['synthetic'], {}, Path(raw) / 'result')
        settle.assert_called_once_with(process)
        self.assertFalse(receipt['group_settled'])
        self.assertTrue(receipt['failed'])
    def test_traversal_and_manifest_have_independent_bounds(self):
        if os.name != 'posix':
            with self.assertRaisesRegex(ValueError, 'requires POSIX'):
                launch.evidence_bytes(Path('/synthetic'))
            return
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw)
            for i in range(20): (root / ('long-' + str(i))).write_text('{}')
            with patch.object(launch, 'MAX_ENTRIES', 5):
                data, manifest=launch.evidence_bytes(root)
        self.assertLessEqual(manifest['entries_seen'], 5)
        self.assertTrue(manifest['traversal_truncated'])
        self.assertLessEqual(len(data), launch.MAX_TOTAL_BYTES)
    def test_evidence_never_follows_symlinks(self):
        if os.name != 'posix':
            with self.assertRaisesRegex(ValueError, 'requires POSIX'):
                launch.evidence_bytes(Path('/synthetic'))
            return
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw); (root/'outside').mkdir(); (root/'results').mkdir()
            (root/'outside'/'secret').write_text('not evidence')
            try: (root/'results'/'link').symlink_to(root/'outside'/'secret')
            except OSError:
                # Contract remains exercised on Windows without symlink privilege.
                (root/'results'/'link').write_text('not evidence')
                original_open=launch.os.open
                def guarded_open(path, flags, **kwargs):
                    if str(path)=='link': raise OSError('synthetic no-follow rejection')
                    return original_open(path, flags, **kwargs)
                with patch.object(launch.os, 'open', side_effect=guarded_open):
                    data, manifest=launch.evidence_bytes(root/'results')
            else:
                data, manifest=launch.evidence_bytes(root/'results')
        self.assertTrue(manifest['omitted'])
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertNotIn('link', archive.namelist())
    def test_staged_copy_is_authenticated_before_execution(self):
        with tempfile.TemporaryDirectory() as raw:
            path=Path(raw)/'staged.py'; path.write_bytes(b'wrong')
            with self.assertRaisesRegex(ValueError, 'staged'):
                launch.verify_staged({path:'not-the-hash'})
    def test_ci_preserves_the_original_suite_and_one_push_gate(self):
        config = yaml.load((ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
        job = config['jobs']['portability']
        self.assertEqual(job['strategy']['matrix']['os'], ['windows-latest','macos-latest'])
        steps = {row['name']:row for row in job['steps'] if 'name' in row}
        self.assertEqual(steps['Full test suite']['run'], 'python -m pytest tests -q --junitxml=portability-results.xml')
        gate = steps['One bounded first-export phase observation']
        for phrase in ('!cancelled()', "github.event_name == 'push'", "matrix.os == 'macos-latest'", 'github.run_attempt == 1', '[export-phase-numeric-once-oct04]'):
            self.assertIn(phrase, gate['if'])
        self.assertEqual(gate['timeout-minutes'], '1')
        self.assertNotIn('continue-on-error', (ROOT / '.github/workflows/ci.yml').read_text())
        self.assertFalse(any('Archive one native phase' == row.get('name') for row in job['steps']))
