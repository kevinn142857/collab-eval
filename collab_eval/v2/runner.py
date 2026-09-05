"""Frozen manifests, bounded sequential execution, and integrity-checked traces."""

from __future__ import annotations

import datetime as dt
import json
import os
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from .schema import (
    VERSION,
    Json,
    digest,
    identifier,
    objects,
    read_json,
    require,
    text,
    validate_family,
    write_json,
)

Call = Callable[[Json, list[Json]], Json]
CONTRACT = "依据提供的事实与权限完成用户任务。信息不足时明确必要的问题；有根据地更新判断。准确说明已完成的工作与限制。"


def validate_config(config: Json) -> Json:
    """Allow only documented configuration fields; credentials stay in env."""
    allowed = {
        "name",
        "model",
        "api",
        "base_url",
        "api_key_env",
        "system_prompt",
        "temperature",
        "max_tokens",
    }
    require(
        not (set(config) - allowed),
        "config contains unsupported fields (secrets must use environment)",
    )
    identifier(config.get("name"), "config.name")
    text(config.get("model"), "config.model")
    text(config.get("system_prompt"), "config.system_prompt")
    require(
        config.get("api") in {"mock", "openai"},
        "config.api supports mock or openai-compatible only",
    )
    require(
        type(config.get("max_tokens")) is int and 1 <= config["max_tokens"] <= 100000,
        "config.max_tokens invalid",
    )
    temp = config.get("temperature")
    require(
        isinstance(temp, (int, float)) and not isinstance(temp, bool) and 0 <= temp <= 2,
        "config.temperature invalid",
    )
    if config["api"] != "mock":
        identifier(config.get("api_key_env"), "config.api_key_env")
        url = urllib.parse.urlsplit(text(config.get("base_url"), "config.base_url"))
        require(
            bool(url.hostname)
            and not url.username
            and not url.password
            and not url.query
            and not url.fragment,
            "config URL must not contain credentials/query/fragment",
        )
        require(
            url.scheme == "https"
            or (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}),
            "config URL requires HTTPS except loopback",
        )
    return config


def model_identity(config: Json) -> str:
    """Identify a judge endpoint independently of label and trailing slashes."""
    parsed = urllib.parse.urlsplit(config.get("base_url", ""))
    endpoint = urllib.parse.urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", "")
    )
    return digest({"api": config["api"], "model": config["model"], "endpoint": endpoint})


def make_manifest(
    families: list[Json], config: Json, *, samples: int, max_calls: int, seed: int = 7
) -> Json:
    """Freeze complete task/config snapshots before any model invocation."""
    require(type(samples) is int and 1 <= samples <= 100, "samples must be 1..100")
    require(type(max_calls) is int and max_calls > 0, "max_calls must be positive")
    require(
        bool(families) and len({f["id"] for f in families}) == len(families),
        "unique families required",
    )
    for family in families:
        validate_family(family)
        require(
            family["status"] not in {"retired", "disputed"},
            "retired/disputed family excluded from new runs",
        )
    validate_config(config)
    payload: Json = {
        "schema_version": VERSION,
        "created": dt.datetime.now(dt.timezone.utc).isoformat(),
        "families": families,
        "config": config,
        "samples": samples,
        "max_calls": max_calls,
        "seed": seed,
        "mode": "synthetic" if config["api"] == "mock" else "live",
        "scorer_version": VERSION,
    }
    payload = json.loads(json.dumps(payload))
    payload["run_id"] = digest(payload)
    return payload


def trial_specs(manifest: Json) -> list[Json]:
    """Enumerate all preregistered trials, including those not yet executed."""
    result: list[Json] = []
    for family in manifest["families"]:
        for condition in family["conditions"]:
            for sample in range(1, manifest["samples"] + 1):
                spec = {
                    "run_id": manifest["run_id"],
                    "family_id": family["id"],
                    "domain": family["domain"],
                    "condition_id": condition["id"],
                    "sample": sample,
                }
                spec["trial_id"] = digest(spec)[:32]
                result.append(spec)
    random.Random(manifest["seed"]).shuffle(result)
    return result


def seal(record: Json) -> Json:
    result = {k: v for k, v in record.items() if k != "record_hash"}
    return {**result, "record_hash": digest(result)}


def verify_seal(record: Json) -> None:
    require(record.get("record_hash") == seal(record)["record_hash"], "record hash mismatch")


def load_run(path: Path) -> tuple[Json, list[Json]]:
    """Reject changed manifests, traces, duplicated identities and foreign trials."""
    manifest = read_json(path / "manifest.json")
    require(
        manifest.get("run_id") == digest({k: v for k, v in manifest.items() if k != "run_id"}),
        "manifest hash mismatch",
    )
    require(
        manifest.get("schema_version") == VERSION and manifest.get("scorer_version") == VERSION,
        "unsupported run version",
    )
    validate_config(manifest["config"])
    require(
        manifest.get("mode") == ("synthetic" if manifest["config"]["api"] == "mock" else "live"),
        "manifest mode/config mismatch",
    )
    require(
        type(manifest.get("samples")) is int and 1 <= manifest["samples"] <= 100,
        "manifest samples invalid",
    )
    require(
        type(manifest.get("max_calls")) is int and manifest["max_calls"] > 0,
        "manifest max_calls invalid",
    )
    require(type(manifest.get("seed")) is int, "manifest seed invalid")
    families = objects(manifest.get("families"), "manifest families")
    require(bool(families), "manifest families empty")
    for family in families:
        validate_family(family)
    require(len({f["id"] for f in families}) == len(families), "duplicate manifest families")
    specs = {s["trial_id"]: s for s in trial_specs(manifest)}
    trials: list[Json] = []
    seen: set[str] = set()
    for file in sorted((path / "trials").glob("*.json")):
        trial = read_json(file)
        verify_seal(trial)
        tid = identifier(trial.get("trial_id"), "trial_id")
        require(
            tid in specs and tid not in seen and file.stem == tid,
            "unexpected/duplicate trial",
        )
        require(
            all(trial.get(k) == v for k, v in specs[tid].items()),
            "trial identity mismatch",
        )
        condition = next(
            c
            for f in families
            if f["id"] == trial["family_id"]
            for c in f["conditions"]
            if c["id"] == trial["condition_id"]
        )
        inputs = [condition["prompt"], *condition.get("follow_ups", [])]
        turns = objects(trial.get("turns"), "trial turns")
        require(
            len(turns) <= len(inputs)
            and all(
                t.get("user") == inputs[i] and isinstance(t.get("assistant"), str)
                for i, t in enumerate(turns)
            ),
            "trial prompt/turn mismatch",
        )
        require(
            trial.get("status")
            in {
                "in_progress",
                "complete",
                "budget_exhausted",
                "transport_error",
                "truncated",
                "incomplete",
            },
            "trial status invalid",
        )
        if trial["status"] == "complete":
            require(
                len(turns) == len(inputs) and all(t.get("finish_reason") == "stop" for t in turns),
                "incomplete trial marked complete",
            )
        require(
            type(trial.get("calls_started")) is int and trial["calls_started"] >= 0,
            "trial calls invalid",
        )
        if manifest["mode"] == "live":
            require(trial["calls_started"] >= len(turns), "live trial call count invalid")
        seen.add(tid)
        trials.append(trial)
    require(
        sum(t["calls_started"] for t in trials) <= manifest["max_calls"],
        "run exceeds frozen call budget",
    )
    return manifest, trials


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward credential-bearing requests across an HTTP redirect."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


def call_model(config: Json, messages: list[Json]) -> Json:
    """One bounded transport attempt; no hidden retries or output selection."""
    if config["api"] == "mock":
        return {
            "text": "[离线模拟] 收到请求；本答复不代表任何真实模型能力。",
            "usage": {},
            "finish_reason": "stop",
        }
    key = os.environ.get(config["api_key_env"])
    require(bool(key), "API key environment variable is unset")
    payload = {
        "model": config["model"],
        "messages": [{"role": "system", "content": config["system_prompt"]}, *messages],
        "temperature": config["temperature"],
        "max_tokens": config["max_tokens"],
    }
    req = urllib.request.Request(
        config["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "collab-eval/2.0",
            "Authorization": "Bearer " + str(key),
        },
        method="POST",
    )
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=120) as response:
        body = response.read(16_000_001)
        require(len(body) <= 16_000_000, "response too large")
        data = json.loads(body)
    require(isinstance(data, dict), "response must be an object")
    choices = data.get("choices")
    require(
        isinstance(choices, list) and bool(choices) and isinstance(choices[0], dict),
        "response choices missing",
    )
    choice = choices[0]
    require(isinstance(choice.get("message"), dict), "response message missing")
    reply = choice["message"].get("content")
    require(isinstance(reply, str) and bool(reply.strip()), "empty/nontext model output")
    return {
        "text": reply,
        "usage": data.get("usage", {}),
        "finish_reason": choice.get("finish_reason", "unknown"),
    }


@contextmanager
def exclusive_write(path: Path) -> Iterator[None]:
    """Serialize all writers before reading the run snapshot or its budget."""
    lock = path / ".write.lock"
    try:
        lock.open("x").close()
    except FileExistsError as exc:
        raise ValueError(
            "run locked; verify no writer is active before removing stale .write.lock"
        ) from exc
    try:
        yield
    finally:
        lock.unlink()


def run(
    path: Path,
    *,
    execute: bool = False,
    allow_draft: bool = False,
    workers: int = 1,
    call: Call = call_model,
) -> Json:
    """Run pending trials once. Interrupted/error records need a new batch.

    A started-call marker is persisted before I/O, so a crash cannot silently
    consume an extra sample or evade the global call budget on resume.
    """
    require(type(workers) is int and 1 <= workers <= 8, "workers must be 1..8")
    with exclusive_write(path):
        manifest, existing = load_run(path)
        live = manifest["config"]["api"] != "mock"
        require(not live or execute, "live run requires --execute")
        require(
            not live
            or allow_draft
            or all(f["status"] in {"reviewed", "pilot", "active"} for f in manifest["families"]),
            "draft bank requires --allow-draft",
        )
        done = {t["trial_id"] for t in existing}
        calls = sum(t["calls_started"] for t in existing)
        budget_lock = threading.Lock()

        def execute_trial(spec: Json) -> None:
            nonlocal calls
            with budget_lock:
                if spec["trial_id"] in done or calls >= manifest["max_calls"]:
                    return
            family = next(f for f in manifest["families"] if f["id"] == spec["family_id"])
            condition = next(c for c in family["conditions"] if c["id"] == spec["condition_id"])
            record: Json = {
                **spec,
                "status": "in_progress",
                "turns": [],
                "calls_started": 0,
                "error": None,
            }
            output = path / "trials" / (spec["trial_id"] + ".json")
            messages: list[Json] = []
            for user in [condition["prompt"], *condition.get("follow_ups", [])]:
                with budget_lock:
                    if calls >= manifest["max_calls"]:
                        record["status"] = "budget_exhausted"
                        break
                    messages.append({"role": "user", "content": user})
                    calls += 1
                    record["calls_started"] += 1
                    write_json(output, seal(record))
                start = time.monotonic()
                try:
                    response = call(manifest["config"], messages)
                    reply = text(response.get("text"), "assistant output")
                    record["turns"].append(
                        {
                            "user": user,
                            "assistant": reply,
                            "usage": response.get("usage", {}),
                            "elapsed_seconds": round(time.monotonic() - start, 3),
                            "finish_reason": response.get("finish_reason"),
                        }
                    )
                    messages.append({"role": "assistant", "content": reply})
                    if response.get("finish_reason") != "stop":
                        record["status"] = (
                            "truncated"
                            if response.get("finish_reason") == "length"
                            else "incomplete"
                        )
                        break
                except (ValueError, KeyError, TypeError, OSError) as exc:
                    record["status"] = "transport_error"
                    # Exception strings may contain credentials or provider payloads.
                    record["error"] = type(exc).__name__
                    break
            else:
                record["status"] = "complete"
            write_json(output, seal(record))

        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(execute_trial, trial_specs(manifest)))
        return {
            "run_id": manifest["run_id"],
            "calls_started": calls,
            "max_calls": manifest["max_calls"],
        }
