"""Guard: gateway_bench.py must behave as a real gate (non-zero on failure).

Before this fix the bench always exited 0: with $MELIOUS_API_KEY unset it
issued 12 doomed live calls and still "passed"; a failing resilience probe
was also reported with exit 0. Functions are extracted with ast so no live
gateway call is ever made under pytest.
"""
import ast
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "gateway_bench.py")


def _load(*names):
    tree = ast.parse(open(SCRIPT, encoding="utf-8").read())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    ns = {"os": os, "argparse": __import__("argparse"), "__doc__": "gateway bench"}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), SCRIPT, "exec"), ns)
    return ns


def test_exit_code_contract():
    ec = _load("exit_code")["exit_code"]
    ok = {"resilience": {"a": {"pass": True}, "b": {"pass": True}}}
    bad = {"resilience": {"a": {"pass": True}, "b": {"pass": False}}}
    assert ec(ok, key_present=True, probes_only=False) == 0
    assert ec(ok, key_present=False, probes_only=True) == 0
    assert ec(bad, key_present=True, probes_only=False) == 1
    assert ec({"resilience": {}}, key_present=True, probes_only=True) == 1
    assert ec(ok, key_present=False, probes_only=False) == 2


def test_parse_args_positional_and_flags():
    pa = _load("parse_args")["parse_args"]
    a = pa(["/tmp/x", "--output", "r.json", "--probes-only"])
    assert (a.root, a.output, a.probes_only) == ("/tmp/x", "r.json", True)
    b = pa([])
    assert b.output is None and b.probes_only is False


def test_live_mode_without_key_exits_2_and_writes_nothing(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "MELIOUS_API_KEY"}
    out = tmp_path / "gw.json"
    r = subprocess.run([sys.executable, SCRIPT, ROOT, "--output", str(out)],
                       env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 2, r.stderr
    assert not out.exists()


def test_probes_only_offline_passes(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "MELIOUS_API_KEY"}
    out = tmp_path / "gw.json"
    r = subprocess.run([sys.executable, SCRIPT, ROOT, "--probes-only", "--output", str(out)],
                       env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert out.exists()
