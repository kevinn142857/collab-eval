"""Immutable runs, error visibility, and bounded external calls."""

import pytest
from test_v2_scoring import family

from collab_eval.v2.runner import load_run, make_manifest, run, trial_specs
from collab_eval.v2.schema import read_json, write_json


def config():
    return {
        "name": "test",
        "model": "mock",
        "api": "mock",
        "system_prompt": "协作契约",
        "max_tokens": 100,
        "temperature": 0,
    }


def test_snapshots_and_run_id_are_verified(tmp_path):
    manifest = make_manifest([family()], config(), samples=1, max_calls=2)
    write_json(tmp_path / "manifest.json", manifest)
    manifest["families"][0]["title"] = "tampered"
    write_json(tmp_path / "manifest.json", manifest)
    with pytest.raises(ValueError, match="hash"):
        load_run(tmp_path)


def test_resume_does_not_rerun_valid_or_error_trials(tmp_path):
    m = make_manifest([family()], config(), samples=1, max_calls=2)
    write_json(tmp_path / "manifest.json", m)
    calls = []

    def call(c, messages):
        calls.append(messages)
        return {"text": "答复", "finish_reason": "stop", "usage": {}}

    run(tmp_path, call=call)
    run(tmp_path, call=call)
    assert len(calls) == 2
    assert len(load_run(tmp_path)[1]) == 1


def test_budget_is_global_and_missing_trials_stay_expected(tmp_path):
    m = make_manifest([family()], config(), samples=2, max_calls=1)
    write_json(tmp_path / "manifest.json", m)
    run(tmp_path)
    manifest, trials = load_run(tmp_path)
    assert len(trial_specs(manifest)) == 2
    assert sum(t["calls_started"] for t in trials) == 1
    assert all(t["status"] != "complete" for t in trials)


def test_invalid_or_secret_configuration_rejected():
    c = config()
    c["api_key"] = "never-persist"
    with pytest.raises(ValueError, match="config"):
        make_manifest([family()], c, samples=1, max_calls=2)


def test_live_requires_explicit_execution_and_draft_opt_in(tmp_path):
    c = config()
    c.update(api="openai", base_url="https://example.com/v1", api_key_env="TEST_KEY")
    m = make_manifest([family()], c, samples=1, max_calls=2)
    write_json(tmp_path / "manifest.json", m)
    with pytest.raises(ValueError, match="execute"):
        run(tmp_path)
    with pytest.raises(ValueError, match="draft"):
        run(tmp_path, execute=True)


def test_truncated_output_never_counts_complete(tmp_path):
    write_json(
        tmp_path / "manifest.json",
        make_manifest([family()], config(), samples=1, max_calls=2),
    )
    run(
        tmp_path,
        call=lambda c, m: {"text": "partial", "finish_reason": "length", "usage": {}},
    )
    assert load_run(tmp_path)[1][0]["status"] == "truncated"


def test_trial_tampering_rejected(tmp_path):
    write_json(
        tmp_path / "manifest.json",
        make_manifest([family()], config(), samples=1, max_calls=2),
    )
    run(tmp_path)
    path = next((tmp_path / "trials").glob("*.json"))
    t = read_json(path)
    t["turns"][0]["assistant"] = "tampered"
    write_json(path, t)
    with pytest.raises(ValueError, match="hash"):
        load_run(tmp_path)


def test_write_lock_precedes_snapshot(tmp_path, monkeypatch):
    import collab_eval.v2.runner as runner

    write_json(
        tmp_path / "manifest.json",
        make_manifest([family()], config(), samples=1, max_calls=2),
    )
    original = runner.load_run

    def checked(path):
        assert (path / ".write.lock").exists(), "snapshot before lock"
        return original(path)

    monkeypatch.setattr(runner, "load_run", checked)
    runner.run(tmp_path)


def test_forged_synthetic_mode_cannot_trigger_live_calls(tmp_path):
    from collab_eval.v2.schema import digest

    c = config()
    c.update(api="openai", base_url="https://example.com/v1", api_key_env="TEST_KEY")
    m = make_manifest([family()], c, samples=1, max_calls=2)
    m["mode"] = "synthetic"
    m["run_id"] = digest({k: v for k, v in m.items() if k != "run_id"})
    write_json(tmp_path / "manifest.json", m)
    calls = []
    with pytest.raises(ValueError, match="mode"):
        run(tmp_path, call=lambda c, m: calls.append(1))
    assert not calls


def test_rehashed_invalid_manifest_is_rejected(tmp_path):
    from collab_eval.v2.schema import digest

    for field, value in [("samples", 0), ("max_calls", -1)]:
        m = make_manifest([family()], config(), samples=1, max_calls=2)
        m[field] = value
        m["run_id"] = digest({k: v for k, v in m.items() if k != "run_id"})
        write_json(tmp_path / "manifest.json", m)
        with pytest.raises(ValueError, match=field):
            load_run(tmp_path)


def test_malformed_http_choices_become_validation_error(monkeypatch):
    import collab_eval.v2.runner as runner

    c = config()
    c.update(api="openai", base_url="https://example.com/v1", api_key_env="TEST_V2_DUMMY")
    monkeypatch.setenv("TEST_V2_DUMMY", "test-only-placeholder")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return b'{"choices": []}'

    class Opener:
        def open(self, request, timeout):
            return Response()

    monkeypatch.setattr(runner.urllib.request, "build_opener", lambda *a: Opener())
    with pytest.raises(ValueError, match="choices"):
        runner.call_model(c, [{"role": "user", "content": "test"}])
