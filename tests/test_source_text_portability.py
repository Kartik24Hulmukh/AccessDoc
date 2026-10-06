"""Scoped source-test portability without changing the process UTF-8 mode."""
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import test_dependency_snapshot_audit as dependency_tests
from tests import test_pending_evidence as pending_tests

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ("requirements.txt", "pyproject.toml")


def git(root, *args, input=None):
    return subprocess.check_output(["git", "-C", str(root), *args], input=input,
                                   stderr=subprocess.PIPE)


def commit_inputs(root):
    # Test-only Git objects live in a temporary fixture, never the source repo.
    git(root, "-c", "core.autocrlf=false", "add", "--", *INPUTS)
    tree = git(root, "write-tree").decode("ascii").strip()
    commit = git(root, "-c", "user.name=Portability Fixture",
                 "-c", "user.email=fixture@example.invalid", "commit-tree", tree,
                 input=b"source fixture\n").decode("ascii").strip()
    git(root, "update-ref", "HEAD", commit)


class SourceTextPortabilityTests(unittest.TestCase):
    def test_explicit_utf8_readers_under_cp1252_default(self):
        original = Path.read_text
        encodings = []

        def cp1252_default(path, encoding=None, errors=None, **kwargs):
            encodings.append(encoding)
            return original(path, encoding="cp1252" if encoding is None else encoding,
                            errors=errors, **kwargs)

        with patch.object(Path, "read_text", cp1252_default):
            source = dependency_tests.SupplyChainSourceContracts()
            source.test_docs_distinguish_portable_installer_from_native_locks()
            source.test_notices_and_scope_doc_are_truthful()
            pending_tests.PendingEvidenceTests().test_manual_format_guidance_is_not_plain_prose()
        self.assertTrue(encodings)
        self.assertEqual(set(encodings), {"utf-8"})

    def source_fixture(self, root):
        git(root, "init", "-q")
        for name in INPUTS:
            (root / name).write_bytes(git(ROOT, "show", "HEAD:" + name))
        (root / "sbom.json").write_bytes((ROOT / "sbom.json").read_bytes())
        commit_inputs(root)

    def check_source(self, root):
        with patch.object(dependency_tests, "ROOT", root):
            dependency_tests.SupplyChainSourceContracts().test_sbom_binds_exact_dependency_input_bytes()

    def test_source_contract_uses_committed_blobs_not_crlf_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.source_fixture(root)
            self.check_source(root)
            committed = {name: git(root, "show", "HEAD:" + name) for name in INPUTS}
            # Force fresh materialization; an up-to-date index stat can retain
            # existing LF files even when checkout-index is passed --force.
            for name in INPUTS:
                (root / name).unlink()
            git(root, "-c", "core.autocrlf=true", "checkout-index", "--all", "--force")
            for name, data in committed.items():
                self.assertNotIn(b"\r", data)
                self.assertEqual((root / name).read_bytes(), data.replace(b"\n", b"\r\n"))
                self.assertNotEqual(hashlib.sha256(data).digest(),
                                    hashlib.sha256((root / name).read_bytes()).digest())
            self.check_source(root)
            for name, data in committed.items():
                self.assertEqual((root / name).read_bytes(), data.replace(b"\n", b"\r\n"))

    def test_source_contract_rejects_changed_committed_input(self):
        for name in INPUTS:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.source_fixture(root)
                original = (root / name).read_bytes()
                changed = original.replace(b"reportlab>=4.0.0", b"reportlab>=4.0.1", 1)
                self.assertNotEqual(original, changed)
                (root / name).write_bytes(changed)
                commit_inputs(root)
                # Old working bytes cannot hide a changed candidate HEAD blob.
                (root / name).write_bytes(original)
                with self.assertRaises(AssertionError):
                    self.check_source(root)

    def test_source_contract_rejects_wrong_or_missing_recorded_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.source_fixture(root)
            original = json.loads((root / "sbom.json").read_text(encoding="utf-8"))
            for suffix in ("sha256", "git-blob-sha1"):
                for missing in (False, True):
                    with self.subTest(suffix=suffix, missing=missing):
                        bom = json.loads(json.dumps(original))
                        props = bom["metadata"]["component"]["properties"]
                        name = "accessdoc:source:requirements.txt:" + suffix
                        prop = next(p for p in props if p["name"] == name)
                        if missing:
                            props.remove(prop)
                        else:
                            prop["value"] = "0" * len(prop["value"])
                        (root / "sbom.json").write_text(json.dumps(bom), encoding="utf-8")
                        with self.assertRaises(KeyError if missing else AssertionError):
                            self.check_source(root)
