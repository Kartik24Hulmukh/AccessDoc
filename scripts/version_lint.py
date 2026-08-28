#!/usr/bin/env python3
"""Enforce that every version reference across active tracked files equals VERSION."""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"

with open(VERSION_FILE, "r", encoding="utf-8") as f:
    expected = f.read().strip()

pattern = re.compile(r"0\.[0-9]+\.[0-9]+-beta\.[0-9]+")
excluded_dirs = {
    ".git", "__pycache__", "node_modules", "docs/plan",
    "docs/launch-study", "examples", "gumloop", "release"
}
excluded_files = {
    "CHANGELOG.md", "ARTIFACT_LEDGER.md", "COMPLETION_LEDGER.md", "GUMLOOP_PROMPTS.md",
    "STATE.md", "ERRATA.md", "GITHUB_PUBLICATION_CHECKLIST.md", "ROADMAP.md",
    "THREAT-MODEL.md", "VERCEL_DEPLOYMENT.md", "signing-plan.md", "self-audit.md",
    "outreach-emails.md", "a11y-weekly.md", "linkedin.md", "test_receipt_schema.py",
    "test_receipt_verifier.py"
}

failed = False
for root, dirs, files in os.walk(ROOT):
    rel_root = Path(root).relative_to(ROOT).as_posix()
    if any(part in (".git", "__pycache__", "node_modules") for part in rel_root.split("/")):
        continue
    if any(rel_root == d or rel_root.startswith(d + "/") for d in excluded_dirs):
        continue
    for f in files:
        if f.endswith(".pyc") or f in excluded_files:
            continue
        filepath = Path(root) / f
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
            for line_no, line in enumerate(content.splitlines(), 1):
                for match in pattern.findall(line):
                    if match != expected:
                        print(f"::error::stale version string in {filepath.relative_to(ROOT)}:{line_no} ({match} != {expected})")
                        failed = True
        except Exception:
            pass

if failed:
    sys.exit(1)
print(f"version-lint OK: all active files match canonical VERSION {expected}")
