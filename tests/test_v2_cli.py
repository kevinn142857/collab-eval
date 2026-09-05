"""Offline end-to-end report and safe rendering contracts."""

import json
import subprocess
import sys

from test_v2_runner import config
from test_v2_scoring import family

from collab_eval.v2.judging import collect
from collab_eval.v2.report import render
from collab_eval.v2.runner import make_manifest, run
from collab_eval.v2.schema import write_json


def test_report_escapes_transcript_html(tmp_path):
    write_json(
        tmp_path / "manifest.json",
        make_manifest([family()], config(), samples=1, max_calls=2),
    )
    run(
        tmp_path,
        call=lambda c, m: {
            "text": "<script>alert(1)</script>",
            "finish_reason": "stop",
        },
    )
    report = collect(tmp_path)
    output = tmp_path / "report.html"
    render(report, output)
    html = output.read_text()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "离线模拟" in html and "待独立人审" in html
    assert "未决" in html


def test_demo_cli_builds_private_labeled_artifacts(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "collab_eval.cli",
            "v2",
            "demo",
            "--out",
            str(tmp_path / "demo"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / "demo" / "report.json").read_text())
    assert report["manifest"]["mode"] == "synthetic"
    assert report["judge_calibrated"] is False
    assert (tmp_path / "demo" / "index.html").exists()
    assert report["summary"]["expected"] > 0


def test_plan_cli_does_not_call_network(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "collab_eval.cli",
            "v2",
            "plan",
            "--out",
            str(tmp_path / "run"),
            "--samples",
            "1",
            "--max-calls",
            "2",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "run" / "manifest.json").exists()
    assert not (tmp_path / "run" / "trials").exists()


def test_human_citation_is_visible_in_report(tmp_path):
    from collab_eval.v2.judging import add_adjudication

    write_json(
        tmp_path / "manifest.json",
        make_manifest([family()], config(), samples=1, max_calls=2),
    )
    run(
        tmp_path,
        call=lambda c, m: {"text": "只保留第一条的修改。", "finish_reason": "stop"},
    )
    r = collect(tmp_path)
    add_adjudication(
        tmp_path,
        {
            "trial_id": r["trials"][0]["trial_id"],
            "criterion_id": "scope",
            "status": "pass",
            "reviewer": "reviewer-1",
            "reason": "范围核对",
            "citations": [{"turn": 2, "quote": "只保留第一条的修改。"}],
        },
    )
    render(collect(tmp_path), tmp_path / "review.html")
    html = (tmp_path / "review.html").read_text()
    assert "人工裁决 · 通过" in html
    assert "第 2 轮：只保留第一条的修改。" in html


def test_report_cannot_overwrite_source_manifest(tmp_path):
    directory = tmp_path / "run"
    write_json(
        directory / "manifest.json", make_manifest([family()], config(), samples=1, max_calls=2)
    )
    before = (directory / "manifest.json").read_bytes()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "collab_eval.cli",
            "v2",
            "report",
            str(directory),
            "--out",
            str(directory / "manifest.html"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert (directory / "manifest.json").read_bytes() == before
