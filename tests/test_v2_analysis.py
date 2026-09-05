"""Hand-calculated coverage and paired-statistics contracts."""

import pytest
from test_v2_runner import config
from test_v2_scoring import family

from collab_eval.v2.analysis import compare_reports, summarize
from collab_eval.v2.runner import make_manifest, trial_specs


def result(spec, state):
    return {
        **spec,
        "status": state,
        "events": {
            "boundary": "not_applicable",
            "friction": "not_applicable",
            "update": "not_applicable",
            "repair": "not_applicable",
        },
        "checks": [],
        "review_required": state == "unresolved",
    }


def test_missing_trials_remain_in_denominator():
    manifest = make_manifest([family()], config(), samples=2, max_calls=4)
    specs = trial_specs(manifest)
    report = summarize(manifest, [result(specs[0], "pass")])
    assert report["summary"]["expected"] == 2
    assert report["summary"]["unresolved"] == 1
    assert report["summary"]["rate_lower"] == 0.5
    assert report["summary"]["rate_upper"] == 1
    assert report["summary"]["ci"] is None


def test_duplicate_trials_rejected():
    m = make_manifest([family()], config(), samples=1, max_calls=2)
    r = result(trial_specs(m)[0], "pass")
    with pytest.raises(ValueError, match="duplicate"):
        summarize(m, [r, r])


def test_repeated_samples_do_not_inflate_family_count():
    m = make_manifest([family()], config(), samples=10, max_calls=20)
    report = summarize(m, [result(s, "pass") for s in trial_specs(m)])
    assert report["summary"]["families"] == 1
    assert report["summary"]["ci"] is None


def test_mismatched_task_versions_cannot_compare():
    f = family()
    m1 = make_manifest([f], config(), samples=1, max_calls=2)
    a = summarize(m1, [])
    f["title"] += "new"
    b = summarize(make_manifest([f], config(), samples=1, max_calls=2), [])
    assert compare_reports(a, b)["status"] == "incomparable"


def test_unresolved_comparison_is_not_equivalence():
    m = make_manifest([family()], config(), samples=2, max_calls=4)
    a, b = summarize(m, []), summarize(m, [])
    comparison = compare_reports(a, b)
    assert comparison["status"] == "insufficient_evidence"
    assert comparison["difference_bounds"] == [-1, 1]


def test_same_judge_pool_with_different_assignments_is_not_comparable():
    m = make_manifest([family()], config(), samples=1, max_calls=2)
    a, b = summarize(m, []), summarize(m, [])
    a["judge_signature"] = b["judge_signature"] = ["x", "y", "z"]
    a["judge_assignments"] = {"family:baseline:1": ["x", "y"]}
    b["judge_assignments"] = {"family:baseline:1": ["x", "z"]}
    assert compare_reports(a, b)["status"] == "incomparable"
