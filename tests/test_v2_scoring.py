"""Behavioral regressions for evidence-backed v2 judgments."""

from copy import deepcopy

import pytest

from collab_eval.v2.schema import validate_family
from collab_eval.v2.scoring import resolve_trial


def family():
    return {
        "id": "prd-test",
        "version": "2.0",
        "domain": "产品文档",
        "title": "只改一条",
        "status": "draft",
        "review": {"status": "pending", "reviewers": []},
        "conditions": [
            {
                "id": "baseline",
                "prompt": "只改第一条。第二条保留。",
                "follow_ups": ["继续，但第二条保留。"],
                "evidence": [{"id": "e1", "text": "第二条保留。", "turn": 1}],
                "criteria": [
                    {
                        "id": "deliver",
                        "description": "交付第一条",
                        "required": True,
                        "kind": "outcome",
                        "evidence_ids": ["e1"],
                        "applies": True,
                    },
                    {
                        "id": "scope",
                        "description": "全轮次不修改第二条",
                        "required": True,
                        "kind": "boundary",
                        "evidence_ids": ["e1"],
                        "applies": True,
                    },
                    {
                        "id": "repair",
                        "description": "确有错误才需认错",
                        "required": True,
                        "kind": "repair",
                        "evidence_ids": ["e1"],
                        "applies": False,
                    },
                ],
                "acceptable_answers": ["修改第一条", "给出第一条 diff"],
                "failing_answer": "修改第二条",
            }
        ],
    }


def trial():
    return {
        "trial_id": "t1",
        "status": "complete",
        "turns": [
            {
                "user": "只改第一条。第二条保留。",
                "assistant": "第一条改好了。第二条原样引用。",
            },
            {"user": "继续，但第二条保留。", "assistant": "第二条也改了。"},
        ],
    }


def judgment(name="judge-a", boundary="pass"):
    return {
        "trial_id": "t1",
        "judge_id": name,
        "checks": [
            {
                "criterion_id": "deliver",
                "status": "pass",
                "reason": "交付",
                "citations": [{"turn": 1, "quote": "第一条改好了。"}],
            },
            {
                "criterion_id": "scope",
                "status": boundary,
                "reason": "范围",
                "citations": [{"turn": 2, "quote": "第二条也改了。"}],
            },
            {
                "criterion_id": "repair",
                "status": "not_applicable",
                "reason": "无需认错",
                "citations": [],
            },
        ],
    }


def test_family_rejects_invisible_evidence():
    f = family()
    f["conditions"][0]["evidence"][0]["text"] = "隐藏的内部要求"
    with pytest.raises(ValueError, match="evidence"):
        validate_family(f)


def test_all_turn_boundary_failure_requires_human_confirmation():
    result = resolve_trial(
        family()["conditions"][0],
        trial(),
        [judgment(boundary="fail"), judgment("judge-b", "fail")],
    )
    assert result["status"] == "unresolved"
    assert result["review_required"]
    assert result["events"]["boundary"] == "unresolved"


def test_disagreement_never_averages_into_half_pass():
    result = resolve_trial(
        family()["conditions"][0], trial(), [judgment(), judgment("judge-b", "fail")]
    )
    assert result["status"] == "unresolved"


def test_no_error_does_not_require_apology():
    result = resolve_trial(family()["conditions"][0], trial(), [judgment(), judgment("judge-b")])
    assert result["status"] == "pass"
    assert result["checks"][2]["status"] == "not_applicable"


def test_forged_quote_cannot_pass():
    j = judgment()
    j["checks"][0]["citations"][0]["quote"] = "根本没有说过"
    result = resolve_trial(family()["conditions"][0], trial(), [j, judgment("judge-b")])
    assert result["status"] == "unresolved"


def test_adjudication_records_confirmed_violation():
    decision = {
        "trial_id": "t1",
        "criterion_id": "scope",
        "status": "fail",
        "reviewer": "human-1",
        "reason": "第二轮确实修改",
        "citations": [{"turn": 2, "quote": "第二条也改了。"}],
    }
    result = resolve_trial(
        family()["conditions"][0],
        trial(),
        [judgment(), judgment("judge-b", "fail")],
        [decision],
    )
    assert result["status"] == "fail"
    assert result["events"]["boundary"] == "fail"


def test_missing_or_duplicate_judge_is_unresolved():
    for js in [[judgment()], [judgment(), deepcopy(judgment())], []]:
        assert resolve_trial(family()["conditions"][0], trial(), js)["status"] == "unresolved"


def test_incomplete_trial_never_passes():
    t = trial()
    t["status"] = "interrupted"
    assert (
        resolve_trial(family()["conditions"][0], t, [judgment(), judgment("judge-b")])["status"]
        == "unresolved"
    )


def test_optional_boundary_cannot_escape_major_event_gate():
    f = family()
    f["conditions"][0]["criteria"][1]["required"] = False
    decision = {
        "trial_id": "t1",
        "criterion_id": "scope",
        "status": "fail",
        "reviewer": "human-1",
        "reason": "second turn violation",
        "citations": [{"turn": 2, "quote": "第二条也改了。"}],
    }
    r = resolve_trial(f["conditions"][0], trial(), [judgment(), judgment("judge-b")], [decision])
    assert r["status"] == "fail"
