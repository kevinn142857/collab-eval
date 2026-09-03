# -*- coding: utf-8 -*-
import glob, os, subprocess, sys, json, tempfile
ROOT = os.path.join(os.path.dirname(__file__), "..")
PY = sys.executable

def test_bank_validates():
    r = subprocess.run([PY, "-m", "collab_eval.cli", "validate"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

def test_mock_runner_all_scenarios(tmp_path):
    scns = sorted(glob.glob(os.path.join(ROOT, "scenarios", "L1", "*.yaml")))
    assert scns
    providers = tmp_path / "providers.yaml"
    providers.write_text("providers:\n  - name: mock\n    api: mock\n    model: echo\n", encoding="utf-8")
    for s in scns:
        r = subprocess.run([PY, "-m", "collab_eval.cli", "run", "--scenario", s, "--provider", "mock",
                            "--providers", str(providers), "--out", str(tmp_path / "t")], cwd=ROOT, capture_output=True, text=True)
        assert r.returncode == 0, s + "\n" + r.stderr
    assert len(glob.glob(str(tmp_path / "t" / "*" / "mock" / "*.json"))) == len(scns)

def test_aggregate_and_report_from_committed_judgments(tmp_path):
    r = subprocess.run([PY, "-m", "collab_eval.cli", "aggregate", "--out", str(tmp_path / "r.json")], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    data = json.load(open(tmp_path / "r.json", encoding="utf-8"))
    assert data["models"] and data["kappa_checklist"] is not None
