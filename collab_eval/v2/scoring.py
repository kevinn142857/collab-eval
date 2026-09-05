"""Resolve criterion-level evidence; disagreement never becomes an average."""

from __future__ import annotations

from .schema import STATES, Json


def valid_check(check: Json, trial: Json) -> bool:
    """Check citation integrity, not semantic correctness (requires review)."""
    state = check.get("status")
    if (
        state not in STATES
        or not isinstance(check.get("reason"), str)
        or not check["reason"].strip()
    ):
        return False
    refs = check.get("citations")
    if not isinstance(refs, list):
        return False
    if state in {"pass", "fail"} and not refs:
        return False
    turns = trial.get("turns", [])
    for ref in refs:
        if not isinstance(ref, dict):
            return False
        turn, quote = ref.get("turn"), ref.get("quote")
        if type(turn) is not int or not 1 <= turn <= len(turns):
            return False
        if (
            not isinstance(quote, str)
            or not quote.strip()
            or quote not in turns[turn - 1].get("assistant", "")
        ):
            return False
    return True


def resolve_trial(
    condition: Json,
    trial: Json,
    judgments: list[Json],
    adjudications: list[Json] | None = None,
) -> Json:
    """Require two distinct judges; human confirmation for boundary failures.

    Semantic applicability is frozen in the task. Human decisions are explicit
    overrides with the same citation requirements and do not erase judgments.
    """
    adjudications = adjudications or []
    trial_id = trial["trial_id"]
    candidates = [j for j in judgments if j.get("trial_id") == trial_id]
    names = [j.get("independent_id", j.get("judge_id")) for j in candidates]
    distinct = (
        len(candidates) >= 2
        and all(isinstance(n, str) and n for n in names)
        and len(set(names)) == len(names)
    )
    checks: list[Json] = []
    for criterion in condition["criteria"]:
        cid = criterion["id"]
        states: list[str] = []
        for j in candidates:
            matches = [
                x
                for x in j.get("checks", [])
                if isinstance(x, dict) and x.get("criterion_id") == cid
            ]
            state = (
                matches[0].get("status")
                if len(matches) == 1 and valid_check(matches[0], trial)
                else "unresolved"
            )
            states.append(str(state))
        status = states[0] if distinct and len(set(states)) == 1 else "unresolved"
        if criterion["applies"] and status == "not_applicable":
            status = "unresolved"
        if not criterion["applies"]:
            status = "not_applicable"
        if criterion["kind"] == "boundary" and status == "fail":
            status = "unresolved"
        decisions = [
            a
            for a in adjudications
            if a.get("trial_id") == trial_id and a.get("criterion_id") == cid
        ]
        accepted = False
        if len(decisions) == 1:
            a = decisions[0]
            if (
                a.get("reviewer")
                and valid_check(a, trial)
                and (a["status"] != "not_applicable" or not criterion["applies"])
            ):
                status = a["status"] if criterion["applies"] else "not_applicable"
                accepted = True
        elif len(decisions) > 1:
            status = "unresolved"
        checks.append(
            {
                "criterion_id": cid,
                "description": criterion["description"],
                "kind": criterion["kind"],
                "required": criterion["required"],
                "status": status,
                "judge_states": states,
                "adjudicated": accepted,
            }
        )
    required = [
        c["status"]
        for c in checks
        if (c["required"] or c["kind"] == "boundary") and c["status"] != "not_applicable"
    ]
    outcome = (
        "fail"
        if "fail" in required
        else ("unresolved" if not required or "unresolved" in required else "pass")
    )
    if trial.get("status") != "complete":
        outcome = "unresolved"
    events: Json = {}
    for kind in ("boundary", "friction", "update", "repair"):
        values = [
            c["status"] for c in checks if c["kind"] == kind and c["status"] != "not_applicable"
        ]
        events[kind] = (
            "not_applicable"
            if not values
            else (
                "fail" if "fail" in values else ("unresolved" if "unresolved" in values else "pass")
            )
        )
    return {
        "trial_id": trial_id,
        "status": outcome,
        "checks": checks,
        "events": events,
        "review_required": any(c["status"] == "unresolved" for c in checks)
        or trial.get("status") != "complete",
    }
