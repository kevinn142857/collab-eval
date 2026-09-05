"""Strict input validation and stable identities for the v2 data boundary."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

Json = dict[str, Any]
STATES = {"pass", "fail", "not_applicable", "unresolved"}
CONDITIONS = {"baseline", "pressure", "evidence_update", "authorization"}
KINDS = {"outcome", "boundary", "friction", "update", "repair"}
VERSION = "2.0"


def require(ok: bool, message: str) -> None:
    """Reject malformed data without coercing missing fields into success."""
    if not ok:
        raise ValueError(message)


def text(value: Any, label: str) -> str:
    require(
        isinstance(value, str) and bool(value.strip()),
        f"{label}: expected nonempty text",
    )
    return str(value)


def identifier(value: Any, label: str) -> str:
    result = text(value, label)
    require(
        bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", result)),
        f"{label}: invalid identifier",
    )
    return result


def objects(value: Any, label: str) -> list[Json]:
    require(
        isinstance(value, list) and all(isinstance(x, dict) for x in value),
        f"{label}: expected objects",
    )
    return list(value)


def digest(value: Any) -> str:
    """Hash canonical JSON; never include secrets in persisted objects."""
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def read_json(path: Path) -> Json:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{path}: expected object")
    return dict(value)


def write_json(path: Path, value: Json, *, exclusive: bool = False) -> None:
    """Write a JSON artifact, optionally refusing to replace existing evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if exclusive:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(payload)
    else:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(path)


def validate_family(family: Json) -> Json:
    """Validate structure, criterion applicability and evidence visibility."""
    identifier(family.get("id"), "family.id")
    require(family.get("version") == VERSION, "family.version must be 2.0")
    for key in ("domain", "title"):
        text(family.get(key), key)
    require(
        family.get("status") in {"draft", "reviewed", "pilot", "active", "disputed", "retired"},
        "family.status invalid",
    )
    review = family.get("review")
    require(isinstance(review, dict), "review missing")
    assert isinstance(review, dict)
    require(review.get("status") in {"pending", "complete"}, "review.status invalid")
    reviewers = review.get("reviewers")
    require(
        isinstance(reviewers, list) and all(isinstance(x, str) and x.strip() for x in reviewers),
        "reviewers invalid",
    )
    assert isinstance(reviewers, list)
    if family["status"] in {"reviewed", "pilot", "active"}:
        require(
            review["status"] == "complete" and len(set(reviewers)) >= 2,
            "two independent review records required",
        )
    conditions = objects(family.get("conditions"), "conditions")
    require(bool(conditions), "conditions empty")
    seen: set[str] = set()
    for condition in conditions:
        cid = identifier(condition.get("id"), "condition.id")
        require(cid in CONDITIONS and cid not in seen, "condition duplicated or unknown")
        seen.add(cid)
        prompt = text(condition.get("prompt"), "prompt")
        follow = condition.get("follow_ups", [])
        require(
            isinstance(follow, list) and all(isinstance(x, str) and x.strip() for x in follow),
            "follow_ups invalid",
        )
        inputs = [prompt, *follow]
        evidence = objects(condition.get("evidence"), "evidence")
        eids: set[str] = set()
        for item in evidence:
            eid = identifier(item.get("id"), "evidence.id")
            require(eid not in eids, "duplicate evidence")
            eids.add(eid)
            turn = item.get("turn")
            require(type(turn) is int and 1 <= turn <= len(inputs), "evidence.turn invalid")
            assert isinstance(turn, int)
            require(
                text(item.get("text"), "evidence.text") in inputs[turn - 1],
                "evidence not visible in declared turn",
            )
        checks = objects(condition.get("criteria"), "criteria")
        require(bool(checks), "criteria empty")
        cids: set[str] = set()
        for check in checks:
            key = identifier(check.get("id"), "criterion.id")
            require(key not in cids, "duplicate criterion")
            cids.add(key)
            text(check.get("description"), "criterion.description")
            require(
                type(check.get("required")) is bool and type(check.get("applies")) is bool,
                "criterion booleans required",
            )
            require(check.get("kind") in KINDS, "criterion.kind invalid")
            refs = check.get("evidence_ids")
            require(
                isinstance(refs, list)
                and bool(refs)
                and all(isinstance(x, str) and x in eids for x in refs),
                "criterion evidence reference invalid",
            )
        require(
            any(c["required"] and c["applies"] and c["kind"] == "outcome" for c in checks),
            "required applicable outcome missing",
        )
        answers = condition.get("acceptable_answers")
        require(
            isinstance(answers, list)
            and len(answers) >= 2
            and all(isinstance(x, str) and x.strip() for x in answers),
            "two acceptable answers required",
        )
        text(condition.get("failing_answer"), "failing_answer")
    return family


def load_bank(path: Path) -> list[Json]:
    """Load a bank with unique family IDs, preserving draft/review metadata."""
    files = sorted(path.glob("*.yaml")) if path.is_dir() else [path]
    require(bool(files), "bank is empty")
    result: list[Json] = []
    for file in files:
        value = yaml.safe_load(file.read_text(encoding="utf-8"))
        require(isinstance(value, dict), f"{file}: expected family object")
        result.append(validate_family(value))
    require(len({f["id"] for f in result}) == len(result), "duplicate family IDs")
    return result
