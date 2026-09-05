"""Structural checks; authored expectations still require independent human review."""

import json
from collections import Counter
from pathlib import Path

import yaml

from collab_eval.v2.schema import load_bank

ROOT = Path(__file__).resolve().parents[1]


def test_draft_bank_structure():
    families = load_bank(ROOT / "scenarios/v2")
    assert len(families) == 20
    assert Counter(f["domain"] for f in families) == {
        "产品文档": 4,
        "需求实现": 4,
        "故障排查": 4,
        "数据分析": 4,
        "日常事务": 4,
    }
    assert len({f["id"] for f in families}) == 20
    for family in families:
        assert family["status"] == "draft"
        assert family["version"] == "2.0"
        assert family["review"] == {"status": "pending", "reviewers": []}
        conditions = {c["id"]: c for c in family["conditions"]}
        assert len(family["conditions"]) == 4
        assert set(conditions) == {
            "baseline",
            "pressure",
            "evidence_update",
            "authorization",
        }
        assert conditions["pressure"]["evidence"] == conditions["baseline"]["evidence"]
        assert conditions["pressure"]["prompt"].startswith(conditions["baseline"]["prompt"])
        for condition in conditions.values():
            assert len(set(condition["acceptable_answers"])) >= 2
            evidence = {e["id"]: e for e in condition["evidence"]}
            assert len(evidence) == len(condition["evidence"])
            turns = [condition["prompt"], *condition["follow_ups"]]
            for item in evidence.values():
                assert item["text"] in turns[item["turn"] - 1]
            assert len(condition["criteria"]) >= 3
            for criterion in condition["criteria"]:
                assert criterion["kind"] in {
                    "outcome",
                    "boundary",
                    "friction",
                    "update",
                    "repair",
                }
                assert set(criterion["evidence_ids"]) <= set(evidence)
                assert isinstance(criterion["required"], bool)
                assert isinstance(criterion["applies"], bool)


def test_calibration_examples_are_drafts_with_valid_references():
    payload = json.loads((ROOT / "calibration/v2/cases.json").read_text())
    assert payload["status"] == "draft"
    assert payload["review_status"] == "pending"
    cases = payload["cases"]
    assert len(cases) == 100
    assert len({c["id"] for c in cases}) == 100
    families = {yaml.safe_load(p.read_text())["id"] for p in (ROOT / "scenarios/v2").glob("*.yaml")}
    assert Counter(c["family_id"] for c in cases) == {family: 5 for family in families}
    assert {"pass", "fail"} == {c["expected"] for c in cases}
    for case in cases:
        assert case["condition_id"] in {
            "baseline",
            "pressure",
            "evidence_update",
            "authorization",
        }
        assert case["answer"] and case["reason"] and case["tags"]
