"""Judgment provenance and invalid-response handling."""

import pytest
from test_v2_runner import config
from test_v2_scoring import family

from collab_eval.v2.judging import add_adjudication, collect, judge_run
from collab_eval.v2.runner import make_manifest, run, verify_seal
from collab_eval.v2.schema import write_json


def setup_run(path):
    write_json(
        path / "manifest.json",
        make_manifest([family()], config(), samples=1, max_calls=2),
    )
    run(path)


def test_invalid_judge_json_stays_unresolved_and_is_cached(tmp_path):
    setup_run(tmp_path)
    calls = []

    def invalid(c, m):
        calls.append(1)
        return {"text": "not JSON", "finish_reason": "stop"}

    judge_run(tmp_path, config(), max_calls=1, call=invalid)
    judge_run(tmp_path, config(), max_calls=1, call=invalid)
    assert len(calls) == 1
    report = collect(tmp_path)
    assert report["summary"]["unresolved"] == 1
    assert report["trials"][0]["judgments"][0]["parse_status"] == "invalid"


def test_judge_cannot_self_certify_calibration(tmp_path):
    setup_run(tmp_path)
    assert collect(tmp_path)["judge_calibrated"] is False


def test_forged_human_citation_rejected(tmp_path):
    setup_run(tmp_path)
    report = collect(tmp_path)
    decision = {
        "trial_id": report["trials"][0]["trial_id"],
        "criterion_id": "scope",
        "status": "pass",
        "reviewer": "human",
        "reason": "checked",
        "citations": [{"turn": 1, "quote": "fake"}],
    }
    with pytest.raises(ValueError, match="citation"):
        add_adjudication(tmp_path, decision)


def test_adjudication_is_append_only(tmp_path):
    setup_run(tmp_path)
    row = collect(tmp_path)["trials"][0]
    decision = {
        "trial_id": row["trial_id"],
        "criterion_id": "scope",
        "status": "pass",
        "reviewer": "human",
        "reason": "checked",
        "citations": [{"turn": 1, "quote": row["trace"]["turns"][0]["assistant"]}],
    }
    add_adjudication(tmp_path, decision)
    with pytest.raises(ValueError, match="already"):
        add_adjudication(tmp_path, decision)


def test_trailing_slash_does_not_create_independent_judge(tmp_path):
    setup_run(tmp_path)
    c = config()
    c.update(
        api="openai", base_url="https://example.com/v1", api_key_env="TEST_V2_DUMMY", name="judge-a"
    )

    def callback(c, m):
        return {"text": "invalid", "finish_reason": "stop"}

    judge_run(tmp_path, c, max_calls=1, execute=True, call=callback)
    c.update(name="judge-b", base_url="https://example.com/v1/")
    with pytest.raises(ValueError, match="independent"):
        judge_run(tmp_path, c, max_calls=1, execute=True, call=callback)


def test_report_preserves_sealed_raw_judgments(tmp_path):
    setup_run(tmp_path)
    judge_run(
        tmp_path,
        config(),
        max_calls=1,
        call=lambda c, m: {"text": "invalid", "finish_reason": "stop"},
    )
    report = collect(tmp_path)
    for row in report["trials"]:
        for judgment in row["judgments"]:
            verify_seal(judgment)
            assert "independent_id" not in judgment


def test_complete_fenced_json_is_parsed_but_truncation_is_not(tmp_path):
    import json

    setup_run(tmp_path)
    row = collect(tmp_path)["trials"][0]
    checks = [
        {
            "criterion_id": c["id"],
            "status": "pass" if c["applies"] else "not_applicable",
            "reason": "evidence checked",
            "citations": [{"turn": 1, "quote": row["trace"]["turns"][0]["assistant"]}]
            if c["applies"]
            else [],
        }
        for c in row["condition"]["criteria"]
    ]
    raw = "```json\n" + json.dumps({"checks": checks}) + "\n```"
    c = config()
    judge_run(tmp_path, c, max_calls=1, call=lambda c, m: {"text": raw, "finish_reason": "stop"})
    c.update(name="truncated-judge", model="different-model")
    judge_run(tmp_path, c, max_calls=1, call=lambda c, m: {"text": raw, "finish_reason": "length"})
    judgments = collect(tmp_path)["trials"][0]["judgments"]
    assert sorted(j["parse_status"] for j in judgments) == ["invalid", "valid"]
    assert all(j["raw"] == raw for j in judgments)
    assert {j["finish_reason"] for j in judgments} == {"stop", "length"}
