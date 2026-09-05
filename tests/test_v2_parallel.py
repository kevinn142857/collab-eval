"""Concurrent execution preserves call caps and sealed, unresolved evidence."""

from copy import deepcopy
from threading import Lock

import pytest
from test_v2_runner import config
from test_v2_scoring import family

from collab_eval.v2.judging import collect, judge_run
from collab_eval.v2.leaderboard import build
from collab_eval.v2.runner import load_run, make_manifest, run, verify_seal
from collab_eval.v2.schema import write_json


def bank():
    result = []
    for i in range(8):
        f = deepcopy(family())
        f["id"] = f"family-{i}"
        result.append(f)
    return result


def test_parallel_runner_never_exceeds_global_budget(tmp_path):
    write_json(tmp_path / "manifest.json", make_manifest(bank(), config(), samples=1, max_calls=3))
    called = []
    lock = Lock()

    def callback(c, m):
        with lock:
            called.append(1)
        return {"text": "answer", "finish_reason": "stop"}

    run(tmp_path, workers=8, call=callback)
    manifest, trials = load_run(tmp_path)
    assert len(called) == 3
    assert sum(t["calls_started"] for t in trials) == 3
    for trial in trials:
        verify_seal(trial)
    run(tmp_path, workers=8, call=callback)
    assert len(called) == 3
    assert collect(tmp_path)["summary"]["expected"] == 8


def test_parallel_judges_preserve_cap_and_invalid_records(tmp_path):
    write_json(tmp_path / "manifest.json", make_manifest(bank(), config(), samples=1, max_calls=32))
    run(tmp_path, workers=8)
    judge_run(
        tmp_path,
        config(),
        workers=8,
        max_calls=3,
        call=lambda c, m: {"text": "invalid", "finish_reason": "stop"},
    )
    report = collect(tmp_path)
    records = [j for row in report["trials"] for j in row["judgments"]]
    assert len(records) == 3
    assert report["summary"]["unresolved"] == 8
    for record in records:
        verify_seal(record)


def test_leaderboard_keeps_unjudged_live_data_unresolved(tmp_path):
    source = tmp_path / "source"
    c = config()
    c.update(
        api="openai", model="declared-model", base_url="https://example.com/v1", api_key_env="DUMMY"
    )
    write_json(source / "manifest.json", make_manifest([family()], c, samples=1, max_calls=1))
    run(
        source,
        execute=True,
        allow_draft=True,
        call=lambda c, m: {"text": "answer", "finish_reason": "stop"},
    )
    target = tmp_path / "export" / "index.html"
    data = build([source], target)
    assert data["models"][0]["summary"]["unresolved"] == 1
    assert "0.0%–100.0%" in target.read_text()
    assert "v2 草案真实试测" in target.read_text()
    with pytest.raises(ValueError, match="outside"):
        build([source], source / "index.html")
