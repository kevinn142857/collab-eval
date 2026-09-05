"""V2 CLI: explicit planning, execution, review and offline evidence reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from .analysis import compare_reports
from .judging import JUDGE_SYSTEM, add_adjudication, collect, condition_for, judge_run
from .report import render
from .runner import CONTRACT, make_manifest, run, seal, trial_specs
from .schema import VERSION, Json, digest, load_bank, read_json, require, write_json

ROOT = Path(__file__).resolve().parents[2]


def provider(path: Path | None) -> Json:
    """Read one explicit provider config; no credential discovery."""
    if path is None:
        return {
            "name": "offline-mock",
            "model": "mock",
            "api": "mock",
            "system_prompt": CONTRACT,
            "max_tokens": 2048,
            "temperature": 0,
        }
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    require(isinstance(data, dict), "provider file must be one configuration object")
    return dict(data)


def demo(output: Path, bank: Path) -> Json:
    """Build synthetic fixtures. These never represent human/model evaluation."""
    require(
        not (output / "manifest.json").exists(),
        "demo output already exists; choose a new directory",
    )
    families = load_bank(bank)
    config = provider(None)
    config.update(name="协作报告 · 离线演示", model="synthetic-fixture")
    # Persisted names are safe IDs; display title is separate in the model field.
    config["name"] = "offline-demo"
    manifest = make_manifest(families, config, samples=1, max_calls=10000)
    write_json(output / "manifest.json", manifest, exclusive=True)
    for index, spec in enumerate(
        sorted(trial_specs(manifest), key=lambda s: (s["family_id"], s["condition_id"]))
    ):
        condition = condition_for(manifest, spec)
        family = next(f for f in families if f["id"] == spec["family_id"])
        baseline = next(c for c in family["conditions"] if c["id"] == "baseline")
        updated = next((c for c in family["conditions"] if c["id"] == "evidence_update"), baseline)
        turns = []
        mode = index % 4
        users = [condition["prompt"], *condition.get("follow_ups", [])]
        for i, user in enumerate(users):
            if i == len(users) - 1:
                answer = (
                    condition["failing_answer"] if mode == 1 else condition["acceptable_answers"][0]
                )
            else:
                answer = (baseline if i == 0 else updated)["acceptable_answers"][0]
            turns.append(
                {
                    "user": user,
                    "assistant": answer,
                    "usage": {},
                    "elapsed_seconds": 0,
                    "finish_reason": "stop",
                }
            )
        trial = seal(
            {
                **spec,
                "status": "complete",
                "turns": turns,
                "calls_started": 0,
                "synthetic": True,
            }
        )
        write_json(output / "trials" / (spec["trial_id"] + ".json"), trial, exclusive=True)
        for jidx in range(1 if mode == 2 else 2):
            jc = {
                **provider(None),
                "name": f"synthetic-judge-{jidx}",
                "model": f"synthetic-fixture-{jidx}",
                "system_prompt": JUDGE_SYSTEM,
            }
            checks = []
            for criterion in condition["criteria"]:
                state = "pass"
                if not criterion["applies"]:
                    state = "not_applicable"
                elif mode == 1 and criterion["kind"] == "outcome":
                    state = "fail"
                checks.append(
                    {
                        "criterion_id": criterion["id"],
                        "status": state,
                        "reason": "离线演示的构造判定；未运行语义评委，不能作为校准或模型成绩。",
                        "citations": []
                        if state == "not_applicable"
                        else [{"turn": len(turns), "quote": turns[-1]["assistant"]}],
                    }
                )
            judgment = seal(
                {
                    "trial_id": spec["trial_id"],
                    "trial_hash": trial["record_hash"],
                    "judge_id": jc["name"],
                    "judge_hash": digest(jc),
                    "judge_config": jc,
                    "scorer_version": VERSION,
                    "checks": checks,
                    "parse_status": "synthetic",
                    "raw": json.dumps({"checks": checks}, ensure_ascii=False),
                }
            )
            write_json(
                output / "judgments" / (spec["trial_id"] + f"-{jidx}.json"),
                judgment,
                exclusive=True,
            )
    report = collect(output)
    write_json(output / "report.json", report)
    render(report, output / "index.html")
    return {
        "html": str((output / "index.html").resolve()),
        "mode": "synthetic",
        "families": len(families),
    }


def guard_output(output: Path, runs: list[Path]) -> None:
    """Prevent HTML and companion JSON from replacing immutable evidence."""
    require(output.suffix.lower() == ".html", "report output must use .html")
    destinations = [output.resolve(), output.with_suffix(".json").resolve()]
    for run_path in runs:
        base = run_path.resolve()
        for destination in destinations:
            require(
                destination != (base / "manifest.json").resolve(), "report would overwrite manifest"
            )
            for directory in ("trials", "judgments", "adjudications"):
                root = (base / directory).resolve()
                require(
                    destination != root and root not in destination.parents,
                    "report would overwrite evidence directory",
                )


def main() -> None:
    """Dispatch v2 commands; live APIs are never implicit in report generation."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate draft/reviewed task structures")
    validate.add_argument("--bank", type=Path, default=ROOT / "scenarios/v2")
    plan = commands.add_parser("plan", help="freeze a run without calling APIs")
    plan.add_argument("--bank", type=Path, default=ROOT / "scenarios/v2")
    plan.add_argument("--provider", type=Path)
    plan.add_argument("--samples", type=int, default=1)
    plan.add_argument("--max-calls", type=int, default=400)
    plan.add_argument("--seed", type=int, default=7)
    plan.add_argument("--out", type=Path, required=True)
    execute = commands.add_parser(
        "run", help="execute pending trials; explicit opt-in for live APIs"
    )
    execute.add_argument("directory", type=Path)
    execute.add_argument("--execute", action="store_true")
    execute.add_argument("--allow-draft", action="store_true")
    judge = commands.add_parser(
        "judge", help="send complete traces to one explicitly configured judge"
    )
    judge.add_argument("directory", type=Path)
    judge.add_argument("--provider", type=Path, required=True)
    judge.add_argument("--max-calls", type=int, required=True)
    judge.add_argument("--execute", action="store_true")
    adjudicate = commands.add_parser(
        "adjudicate", help="import an attributed, cited human decision"
    )
    adjudicate.add_argument("directory", type=Path)
    adjudicate.add_argument("--file", type=Path, required=True)
    report_cmd = commands.add_parser("report", help="build a local report from immutable evidence")
    report_cmd.add_argument("directory", type=Path)
    report_cmd.add_argument("--out", type=Path, required=True)
    compare = commands.add_parser("compare", help="paired comparison, B minus A")
    compare.add_argument("--a", type=Path, required=True)
    compare.add_argument("--b", type=Path, required=True)
    compare.add_argument("--margin", type=float, default=0.05)
    compare.add_argument("--out", type=Path, required=True)
    demo_cmd = commands.add_parser("demo", help="synthetic offline demonstration; no model scores")
    demo_cmd.add_argument("--bank", type=Path, default=ROOT / "scenarios/v2")
    demo_cmd.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result: Json
        if args.command == "validate":
            bank = load_bank(args.bank)
            result = {
                "families": len(bank),
                "conditions": sum(len(f["conditions"]) for f in bank),
                "drafts": sum(f["status"] == "draft" for f in bank),
                "note": "结构校验不代表题目或裁判通过人审。",
            }
        elif args.command == "plan":
            bank = load_bank(args.bank)
            manifest = make_manifest(
                bank,
                provider(args.provider),
                samples=args.samples,
                max_calls=args.max_calls,
                seed=args.seed,
            )
            write_json(args.out / "manifest.json", manifest, exclusive=True)
            expected_calls = args.samples * sum(
                1 + len(c.get("follow_ups", [])) for f in bank for c in f["conditions"]
            )
            result = {
                "run_id": manifest["run_id"],
                "trials": len(trial_specs(manifest)),
                "candidate_calls_needed": expected_calls,
                "call_limit": args.max_calls,
                "mode": manifest["mode"],
                "cost": "未估算价格；max_calls 为调用次数上限，每次输出受 max_tokens 限制。",
                "endpoint": manifest["config"].get("base_url", "offline"),
                "note": "运行清单已冻结，尚未调用模型。",
            }
        elif args.command == "run":
            result = run(args.directory, execute=args.execute, allow_draft=args.allow_draft)
        elif args.command == "judge":
            result = judge_run(
                args.directory,
                provider(args.provider),
                max_calls=args.max_calls,
                execute=args.execute,
            )
        elif args.command == "adjudicate":
            result = {"written": str(add_adjudication(args.directory, read_json(args.file)))}
        elif args.command == "report":
            guard_output(args.out, [args.directory])
            report = collect(args.directory)
            render(report, args.out)
            write_json(args.out.with_suffix(".json"), report)
            result = {"html": str(args.out.resolve()), "summary": report["summary"]}
        elif args.command == "compare":
            guard_output(args.out, [args.a, args.b])
            a, b = collect(args.a), collect(args.b)
            comparison = compare_reports(a, b, margin=args.margin)
            render(b, args.out, comparison)
            write_json(args.out.with_suffix(".json"), comparison)
            result = comparison
        else:
            result = demo(args.out, args.bank)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        parser.exit(2, f"v2: {exc}\n")


if __name__ == "__main__":
    main()
