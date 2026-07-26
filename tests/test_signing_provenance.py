"""Validate the sign-evidence workflow YAML has the required provenance inputs.

Phase 8 — Signing Artifact Provenance.

These tests parse .github/workflows/sign-evidence.yml and assert that:
  1. source_run_id is required with NO default (no stale run ID).
  2. artifact_name is required with default accessdoc-ci-bundle.
  3. expected_commit_sha is required with NO default.
  4. The workflow contains a provenance-verification step that checks
     conclusion, repository, workflow file, head SHA, branch, and artifact
     expiry before downloading or signing.
  5. The workflow verifies the receipt accessdoc_version against the
     expected release version.
"""
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "sign-evidence.yml"


def _load_workflow():
    with open(WORKFLOW, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class SigningProvenanceWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(WORKFLOW.is_file(), f"{WORKFLOW} does not exist")
        self.doc = _load_workflow()

    def _inputs(self):
        on = self.doc.get("on") or self.doc.get(True) or {}
        # workflow_dispatch may be a dict or a string
        wd = on.get("workflow_dispatch")
        self.assertIsInstance(wd, dict, "workflow_dispatch trigger missing")
        return wd.get("inputs", {})

    def test_source_run_id_required_no_default(self):
        """source_run_id must be required and have no stale default."""
        inp = self._inputs().get("source_run_id")
        self.assertIsNotNone(inp, "source_run_id input missing")
        self.assertTrue(inp.get("required"), "source_run_id must be required")
        self.assertNotIn("default", inp, "source_run_id must not have a default")

    def test_artifact_name_required_with_default(self):
        """artifact_name must be required with default accessdoc-ci-bundle."""
        inp = self._inputs().get("artifact_name")
        self.assertIsNotNone(inp, "artifact_name input missing")
        self.assertTrue(inp.get("required"), "artifact_name must be required")
        self.assertEqual(
            inp.get("default"),
            "accessdoc-ci-bundle",
            "artifact_name default must be accessdoc-ci-bundle",
        )

    def test_expected_commit_sha_required_no_default(self):
        """expected_commit_sha must be required with no default."""
        inp = self._inputs().get("expected_commit_sha")
        self.assertIsNotNone(inp, "expected_commit_sha input missing")
        self.assertTrue(inp.get("required"), "expected_commit_sha must be required")
        self.assertNotIn("default", inp, "expected_commit_sha must not have a default")

    def test_provenance_verification_step_exists(self):
        """A step must verify run provenance before download."""
        steps = self.doc["jobs"]["sign"]["steps"]
        names = [s.get("name", "") for s in steps]
        joined = " ".join(names).lower()
        self.assertIn(
            "provenance",
            joined,
            "No provenance-verification step found",
        )

    def _provenance_step_run(self):
        steps = self.doc["jobs"]["sign"]["steps"]
        for s in steps:
            name = (s.get("name") or "").lower()
            if "provenance" in name:
                return s.get("run", "")
        self.fail("No provenance step found")

    def test_provenance_checks_conclusion_success(self):
        run = self._provenance_step_run()
        self.assertIn("conclusion", run)
        self.assertIn("success", run)

    def test_provenance_checks_repository(self):
        run = self._provenance_step_run()
        self.assertIn("Kartik24Hulmukh/AccessDoc", run)
        self.assertIn("repository", run.lower())

    def test_provenance_checks_workflow_file(self):
        run = self._provenance_step_run()
        self.assertIn("accessdoc-action.yml", run)
        self.assertIn("workflow", run.lower())

    def test_provenance_checks_head_sha(self):
        run = self._provenance_step_run()
        self.assertIn("head_sha", run)
        self.assertIn("EXPECTED_COMMIT_SHA", run)

    def test_provenance_checks_branch_main(self):
        run = self._provenance_step_run()
        self.assertIn("main", run)
        self.assertIn("head_branch", run)

    def test_provenance_checks_artifact_expiry(self):
        run = self._provenance_step_run()
        self.assertIn("expired", run)

    def test_provenance_rejects_missing_artifact(self):
        run = self._provenance_step_run()
        # The step must reject zero-artifact runs
        self.assertIn("no artifacts", run.lower())

    def test_receipt_version_check_exists(self):
        """The verify step must confirm receipt accessdoc_version matches."""
        steps = self.doc["jobs"]["sign"]["steps"]
        verify_run = ""
        for s in steps:
            name = (s.get("name") or "").lower()
            if "verify" in name and "evidence bundle" in name:
                verify_run = s.get("run", "")
                break
        self.assertTrue(verify_run, "Locate/verify step not found")
        self.assertIn("accessdoc_version", verify_run)
        self.assertIn("EXPECTED_VERSION", verify_run)

    def test_download_after_provenance(self):
        """download-artifact step must come after the provenance step."""
        steps = self.doc["jobs"]["sign"]["steps"]
        names = [(s.get("name") or "").lower() for s in steps]
        prov_idx = next(
            (i for i, n in enumerate(names) if "provenance" in n), None
        )
        dl_idx = next(
            (i for i, s in enumerate(steps)
             if "uses" in s and "download-artifact" in s.get("uses", "")),
            None,
        )
        self.assertIsNotNone(prov_idx, "provenance step not found")
        self.assertIsNotNone(dl_idx, "download-artifact step not found")
        self.assertGreater(
            dl_idx, prov_idx,
            "download-artifact must come after provenance verification",
        )

    def test_sign_after_verify(self):
        """sign step must come after the verify step."""
        steps = self.doc["jobs"]["sign"]["steps"]
        names = [(s.get("name") or "").lower() for s in steps]
        verify_idx = next(
            (i for i, n in enumerate(names) if "evidence bundle" in n), None
        )
        sign_idx = next(
            (i for i, n in enumerate(names) if "sign" in n and "bundle" in n), None
        )
        self.assertIsNotNone(verify_idx, "verify step not found")
        self.assertIsNotNone(sign_idx, "sign step not found")
        self.assertGreater(sign_idx, verify_idx, "sign must come after verify")


if __name__ == "__main__":
    unittest.main()
