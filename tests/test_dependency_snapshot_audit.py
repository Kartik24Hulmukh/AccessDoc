"""Fail-closed snapshot coverage and local-runtime SBOM scope contracts."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class SnapshotAuditTests(unittest.TestCase):
    def validate(self, snapshot, payload):
        from scripts.audit_dependency_snapshot import validate_audit
        return validate_audit(snapshot, payload)

    def valid_payload(self):
        return {"dependencies": [{"name": "demo_pkg", "version": "1.2.3", "vulns": []}]}

    def rejected(self, snapshot, payload):
        from scripts.audit_dependency_snapshot import AuditFailure
        with self.assertRaises(AuditFailure):
            self.validate(snapshot, payload)

    def test_complete_exact_snapshot_passes(self):
        result = self.validate("demo-pkg==1.2.3\n", self.valid_payload())
        self.assertEqual(result, {"packages": 1, "advisory_records": 0, "skipped": 0})

    def test_comments_and_case_normalization(self):
        self.assertEqual(self.validate("# frozen\nDEMO.PKG==1.2.3\n", self.valid_payload())["packages"], 1)

    def test_skipped_dependency_fails(self):
        p = self.valid_payload(); p["dependencies"][0]["skip_reason"] = "package not found"
        self.rejected("demo-pkg==1.2.3", p)

    def test_skip_reason_cannot_be_hidden_with_empty_value(self):
        p = self.valid_payload(); p["dependencies"][0]["skip_reason"] = ""
        self.rejected("demo-pkg==1.2.3", p)

    def test_known_advisory_fails(self):
        p = self.valid_payload(); p["dependencies"][0]["vulns"] = [{"id": "TEST-1"}]
        self.rejected("demo-pkg==1.2.3", p)

    def test_unqueryable_version_fails(self):
        p = self.valid_payload(); p["dependencies"][0].pop("version")
        self.rejected("demo-pkg==1.2.3", p)

    def test_missing_dependency_fails(self):
        self.rejected("demo-pkg==1.2.3\nother==2", self.valid_payload())

    def test_extra_dependency_fails(self):
        p = self.valid_payload(); p["dependencies"].append({"name": "other", "version": "2", "vulns": []})
        self.rejected("demo-pkg==1.2.3", p)

    def test_wrong_version_fails(self):
        self.rejected("demo-pkg==1.2.4", self.valid_payload())

    def test_duplicate_audit_package_fails(self):
        p = self.valid_payload(); p["dependencies"] *= 2
        self.rejected("demo-pkg==1.2.3", p)

    def test_duplicate_snapshot_fails(self):
        self.rejected("demo-pkg==1.2.3\ndemo_pkg==1.2.3", self.valid_payload())

    def test_unpinned_or_direct_url_snapshot_fails(self):
        for snapshot in ["demo-pkg>=1", "demo-pkg @ https://example.invalid/a.whl", "-r other.txt", "demo-pkg==1.2.3; sys_platform == 'win32'"]:
            with self.subTest(snapshot=snapshot): self.rejected(snapshot, self.valid_payload())

    def test_empty_snapshot_or_payload_fails(self):
        self.rejected("", {"dependencies": []})
        self.rejected("demo-pkg==1.2.3", {})

    def test_missing_vulnerability_field_fails(self):
        p = self.valid_payload(); p["dependencies"][0].pop("vulns")
        self.rejected("demo-pkg==1.2.3", p)

    def test_malformed_payload_types_fail(self):
        for payload in [[], {"dependencies": None}, {"dependencies": [{}]}, {"dependencies": ["demo"]}]:
            with self.subTest(payload=payload): self.rejected("demo-pkg==1.2.3", payload)

    def test_cli_fail_closed_on_invalid_json(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); (p/"pins.txt").write_text("demo-pkg==1.2.3"); (p/"audit.json").write_text("not json")
            result = subprocess.run([sys.executable, str(ROOT/"scripts/audit_dependency_snapshot.py"), "--snapshot", str(p/"pins.txt"), "--audit-json", str(p/"audit.json")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Audit gate failed", result.stderr)

    def test_raw_json_duplicate_keys_and_nonfinite_values_fail(self):
        from scripts.audit_dependency_snapshot import AuditFailure, parse_audit_json
        for raw in ['{"dependencies": [], "dependencies": []}',
                    '{"dependencies": [{"name": "a", "name": "b"}]}',
                    '{"dependencies": NaN}', '{"dependencies": Infinity}']:
            with self.subTest(raw=raw), self.assertRaises(AuditFailure):
                parse_audit_json(raw)

    def test_cli_complete_snapshot_passes(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); (p/"pins.txt").write_text("demo-pkg==1.2.3"); (p/"audit.json").write_text(json.dumps(self.valid_payload()))
            result = subprocess.run([sys.executable, str(ROOT/"scripts/audit_dependency_snapshot.py"), "--snapshot", str(p/"pins.txt"), "--audit-json", str(p/"audit.json")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["packages"], 1)


class SupplyChainSourceContracts(unittest.TestCase):
    def test_runtime_sbom_scope_and_exact_inventory(self):
        bom = json.loads((ROOT/"sbom.json").read_text(encoding="utf-8"))
        self.assertEqual(bom["specVersion"], "1.6")
        self.assertEqual(len(bom["components"]), 19)
        names = {x["name"].lower(): x["version"] for x in bom["components"]}
        self.assertNotIn("pip", names)
        self.assertNotIn("pytest", names)
        self.assertNotIn("playwright", names)
        self.assertNotIn("sigstore", names)
        self.assertEqual(names["reportlab"], "5.0.1")
        self.assertTrue(all(x.get("licenses") for x in bom["components"]))

    def test_sbom_binds_exact_dependency_input_bytes(self):
        bom = json.loads((ROOT/"sbom.json").read_text(encoding="utf-8"))
        props = {x["name"]: x["value"] for x in bom["metadata"]["component"].get("properties", [])}
        for name in ["requirements.txt", "pyproject.toml"]:
            # The SBOM binds the current committed source blob, not Git's
            # platform-specific (possibly CRLF) working-tree representation.
            source_bytes = subprocess.check_output(["git", "show", "HEAD:" + name], cwd=ROOT)
            self.assertEqual(props["accessdoc:source:"+name+":sha256"], hashlib.sha256(source_bytes).hexdigest())
            git_blob = b"blob " + str(len(source_bytes)).encode("ascii") + b"\0" + source_bytes
            self.assertEqual(props["accessdoc:source:"+name+":git-blob-sha1"], hashlib.sha1(git_blob, usedforsecurity=False).hexdigest())
        self.assertIn("local", props["accessdoc:inventory:scope"].lower())
        self.assertIn("not", props["accessdoc:inventory:scope"].lower())
        self.assertIn("3.13.14", props["accessdoc:inventory:target"])
        self.assertNotIn("timestamp", bom["metadata"])
        self.assertNotIn("serialNumber", bom)

    def test_ci_separates_runtime_dev_and_installer(self):
        job = yaml.safe_load((ROOT/".github/workflows/ci.yml").read_text(encoding="utf-8"))["jobs"]["dependency-security"]
        self.assertEqual(job["strategy"]["matrix"]["dependency-scope"], ["runtime", "dev"])
        runs = "\n".join(x.get("run", "") for x in job["steps"])
        self.assertIn(".candidate-venv/bin/python -m pip freeze --all", runs)
        self.assertIn(".audit-venv/bin/python -m pip install pip-audit==2.10.1", runs)
        self.assertIn("scripts/audit_dependency_snapshot.py", runs)
        self.assertIn("installer-snapshot.txt", runs)
        self.assertNotIn("|| true", runs)
        self.assertNotIn("--ignore-vuln", runs)
        self.assertTrue(any("dependency-audit.cdx.json" in x.get("with", {}).get("path", "") and x.get("if") == "always()" for x in job["steps"]))

    def test_installer_bootstrap_is_one_verified_universal_wheel_hash(self):
        rows = [line.strip() for line in (ROOT/"requirements-installer.txt").read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")]
        self.assertEqual(rows, ["pip==26.2.1 --hash=sha256:71138adf1f4ca900cdb7d289c21b7494329f2332b6d85f0e1c42108c0384ed3e"])
        text = (ROOT/"requirements-installer.txt").read_text(encoding="utf-8")
        self.assertIn("pip-26.2.1-py3-none-any.whl", text)
        self.assertNotIn("sys_platform", text)
        self.assertNotIn("manylinux", text)

    def test_ci_bootstraps_candidate_and_auditor_before_other_installs(self):
        job = yaml.safe_load((ROOT/".github/workflows/ci.yml").read_text(encoding="utf-8"))["jobs"]["dependency-security"]
        runs = "\n".join(step.get("run", "") for step in job["steps"])
        for env, later in [(".candidate-venv", "--requirement \"$requirement\""),
                           (".audit-venv", "pip-audit==2.10.1")]:
            bootstrap = env + "/bin/python -m pip install --index-url https://pypi.org/simple --require-hashes --only-binary=:all: --no-deps --requirement requirements-installer.txt"
            self.assertIn(bootstrap, runs)
            self.assertLess(runs.index(bootstrap), runs.index(later))
        self.assertNotIn("runtime-linux-cp313.hashlock", runs)

    def test_docs_distinguish_portable_installer_from_native_locks(self):
        doc = (ROOT/"docs/SUPPLY_CHAIN.md").read_text(encoding="utf-8")
        for phrase in ["requirements-installer.txt", "py3-none-any", "both candidate and audit", "transitive/hash lock"]:
            self.assertIn(phrase, doc)

    def test_notices_and_scope_doc_are_truthful(self):
        text = (ROOT/"THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        self.assertNotIn("Version used for verified release: 5.0.0", text)
        self.assertIn("5.0.1", text)
        self.assertIn("not a license-compliance", text)
        doc = (ROOT/"docs/SUPPLY_CHAIN.md").read_text(encoding="utf-8")
        for term in ["Python 3.12", "Windows", "macOS", "container", "installer", "local"]:
            self.assertIn(term, doc)


if __name__ == "__main__":
    unittest.main()
