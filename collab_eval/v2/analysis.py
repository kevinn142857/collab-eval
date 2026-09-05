"""Family-cluster uncertainty, explicit unresolved bounds and paired contrasts."""

from __future__ import annotations

import random
import statistics
from collections import defaultdict

from .runner import trial_specs
from .schema import Json, digest, require


def mean(values: list[float]) -> float:
    return statistics.mean(values)


def family_bounds(rows: list[Json]) -> list[Json]:
    """Equal conditions within family; repetition never creates a new cluster."""
    groups: dict[tuple[str, str], list[Json]] = defaultdict(list)
    for row in rows:
        groups[(row["domain"], row["family_id"])].append(row)
    result: list[Json] = []
    for (domain, fid), items in sorted(groups.items()):
        conditions: dict[str, list[Json]] = defaultdict(list)
        for row in items:
            conditions[row["condition_id"]].append(row)
        lows, highs = [], []
        for values in conditions.values():
            lows.append(mean([float(v["status"] == "pass") for v in values]))
            highs.append(mean([float(v["status"] != "fail") for v in values]))
        result.append(
            {
                "family_id": fid,
                "domain": domain,
                "lower": mean(lows),
                "upper": mean(highs),
            }
        )
    return result


def macro(bounds: list[Json], key: str) -> float:
    domains: dict[str, list[float]] = defaultdict(list)
    for row in bounds:
        domains[row["domain"]].append(float(row[key]))
    return mean([mean(v) for v in domains.values()])


def cluster_interval(
    bounds: list[Json], *, seed: int = 7, iterations: int = 2000
) -> list[float] | None:
    """Stratify by domain and resample independent families as whole clusters.

    This describes task-family variability of the observed trial means, not
    production prevalence or independent judge uncertainty. Unresolved bounds
    propagate through the resampling. Singleton strata cannot estimate variance.
    """
    groups: dict[str, list[Json]] = defaultdict(list)
    for row in bounds:
        groups[row["domain"]].append(row)
    if not groups or any(len(v) < 2 for v in groups.values()):
        return None
    rng = random.Random(seed)
    lowers: list[float] = []
    uppers: list[float] = []
    for _ in range(iterations):
        sample = [rng.choice(items) for items in groups.values() for _ in items]
        lowers.append(macro(sample, "lower"))
        uppers.append(macro(sample, "upper"))
    return [
        sorted(lowers)[int(0.025 * iterations)],
        sorted(uppers)[int(0.975 * iterations)],
    ]


def summarize(manifest: Json, results: list[Json]) -> Json:
    """Include every planned trial; render unresolved outcomes as rate bounds."""
    specs = trial_specs(manifest)
    by_id = {r["trial_id"]: r for r in results}
    require(len(by_id) == len(results), "duplicate trial results")
    require(set(by_id) <= {s["trial_id"] for s in specs}, "foreign trial results")
    rows: list[Json] = []
    for spec in specs:
        family = next(f for f in manifest["families"] if f["id"] == spec["family_id"])
        condition = next(c for c in family["conditions"] if c["id"] == spec["condition_id"])
        default_events = {
            kind: (
                "unresolved"
                if any(c["kind"] == kind and c["applies"] for c in condition["criteria"])
                else "not_applicable"
            )
            for kind in ("boundary", "friction", "update", "repair")
        }
        row = {
            **spec,
            "status": "unresolved",
            "events": default_events,
            "review_required": True,
            "checks": [],
            **by_id.get(spec["trial_id"], {}),
        }
        require(row["status"] in {"pass", "fail", "unresolved"}, "invalid resolved status")
        require(all(row.get(k) == v for k, v in spec.items()), "result identity mismatch")
        rows.append(row)
    bounds = family_bounds(rows)
    totals: Json = {
        "expected": len(rows),
        "families": len(bounds),
        "domains": len({b["domain"] for b in bounds}),
    }
    for state in ("pass", "fail", "unresolved"):
        totals[state] = sum(r["status"] == state for r in rows)
    totals.update(
        rate_lower=macro(bounds, "lower"),
        rate_upper=macro(bounds, "upper"),
        ci=cluster_interval(bounds),
    )
    metrics: Json = {}
    for kind in ("boundary", "friction", "update", "repair"):
        values = [r["events"][kind] for r in rows if r["events"][kind] != "not_applicable"]
        metrics[kind] = {
            "opportunities": len(values),
            "pass": values.count("pass"),
            "fail": values.count("fail"),
            "unresolved": values.count("unresolved"),
        }
    # Pressure and baseline are matched within family and repetition. Report
    # conditional changes alongside the denominator and all-condition rates.
    matching = {(r["family_id"], r["condition_id"], r["sample"]): r for r in rows}
    pressure: Json = {"pairs": 0, "baseline_pass": 0, "harmful": 0, "unresolved": 0}
    for row in rows:
        if row["condition_id"] != "pressure":
            continue
        base = matching.get((row["family_id"], "baseline", row["sample"]))
        if base is None:
            continue
        pressure["pairs"] += 1
        if base["status"] == "pass":
            pressure["baseline_pass"] += 1
            pressure["harmful"] += int(row["status"] == "fail")
            pressure["unresolved"] += int(row["status"] == "unresolved")
    metrics["pressure"] = pressure
    domain_rows = []
    for domain in sorted({r["domain"] for r in rows}):
        subset = [r for r in rows if r["domain"] == domain]
        db = family_bounds(subset)
        domain_rows.append(
            {
                "domain": domain,
                "families": len(db),
                "expected": len(subset),
                "rate_lower": macro(db, "lower"),
                "rate_upper": macro(db, "upper"),
                "ci": cluster_interval(db),
            }
        )
    return {
        "schema_version": "2.0",
        "manifest": manifest,
        "summary": totals,
        "metrics": metrics,
        "domains": domain_rows,
        "families": bounds,
        "trials": rows,
        "comparison_key": digest(
            {
                "families": manifest["families"],
                "samples": manifest["samples"],
                "scorer_version": manifest["scorer_version"],
                "mode": manifest["mode"],
            }
        ),
    }


def compare_reports(a: Json, b: Json, *, margin: float = 0.05) -> Json:
    """Compare B minus A on exactly matched families, conditions and samples."""
    require(0 < margin < 1, "margin must lie between zero and one")
    result: Json = {
        "a": a["manifest"]["config"]["name"],
        "b": b["manifest"]["config"]["name"],
        "margin": margin,
        "status": "incomparable",
        "difference_bounds": None,
        "ci": None,
    }
    if a["comparison_key"] != b["comparison_key"]:
        result["reason"] = "任务快照、采样计划、轨道或计分版本不一致。"
        return result
    # Judge configurations are another comparability axis once present.
    if a.get("judge_signature") != b.get("judge_signature") or a.get("judge_assignments") != b.get(
        "judge_assignments"
    ):
        result["reason"] = "评委配置或逐试验分配不一致。"
        return result
    af = {f["family_id"]: f for f in a["families"]}
    differences = [
        {
            "family_id": f["family_id"],
            "domain": f["domain"],
            "lower": f["lower"] - af[f["family_id"]]["upper"],
            "upper": f["upper"] - af[f["family_id"]]["lower"],
        }
        for f in b["families"]
    ]
    result["difference_bounds"] = [
        macro(differences, "lower"),
        macro(differences, "upper"),
    ]
    interval = cluster_interval(differences)
    result.update(ci=interval, status="insufficient_evidence", families=len(differences))
    qualified = all(
        f["status"] in {"reviewed", "pilot", "active"} for f in a["manifest"]["families"]
    )
    qualified = (
        qualified
        and a["manifest"]["mode"] == "live"
        and a.get("judge_calibrated") is True
        and b.get("judge_calibrated") is True
    )
    result["qualified"] = qualified
    if interval and qualified:
        low, high = interval
        if low > margin:
            result["status"] = "improved"
        elif high < -margin:
            result["status"] = "regressed"
        elif low >= -margin and high <= margin:
            result["status"] = "equivalent_within_margin"
    result["reason"] = "配对差值为 B − A；草案、模拟或未校准评委仅作探索性比较。"
    result["family_differences"] = differences
    return result
