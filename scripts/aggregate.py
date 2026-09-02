#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聚合评委判定：每模型五维均值 + bootstrap 95% CI、评委间一致性（Cohen's Kappa，按清单项汇总）、
与人工黄金集的偏差。输出 results/results.json 与终端摘要。

用法：/usr/bin/python3 scripts/aggregate.py [--golden scripts/golden_manual.yaml]
"""
import argparse, collections, glob, json, os, random, statistics
import yaml

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DIMS = ["intent", "discover", "stance", "ownership"]
DIM_CN = {"intent": "意图", "discover": "发现", "stance": "表态", "ownership": "闭环"}


def flat_checklist(c):
    out = {}
    for k in ("Q1", "Q2", "Q2b", "Q4", "Q5", "Q7", "Q8", "Q9", "Q10", "Q11", "paired_consistent"):
        v = c.get(k)
        if v is not None:
            out[k] = bool(v)
    for p, v in (c.get("Q3") or {}).items():
        out["Q3." + p] = bool(v)
    return out


def cohen_kappa(pairs):
    """pairs: [(a, b)] 布尔对。"""
    if not pairs:
        return None
    n = len(pairs)
    po = sum(1 for a, b in pairs if a == b) / n
    pa = sum(1 for a, _ in pairs if a) / n
    pb = sum(1 for _, b in pairs if b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return None if pe == 1 else round((po - pe) / (1 - pe), 3)


def bootstrap_ci(values, iters=2000, seed=7):
    if len(values) < 2:
        return (None, None)
    rnd = random.Random(seed)
    means = []
    for _ in range(iters):
        sample = [rnd.choice(values) for _ in values]
        means.append(statistics.mean(sample))
    means.sort()
    return (round(means[int(0.025 * iters)], 2), round(means[int(0.975 * iters)], 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judgments", default=os.path.join(ROOT, "judgments"))
    ap.add_argument("--golden", default=os.path.join(ROOT, "scripts", "golden_manual.yaml"))
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "results.json"))
    args = ap.parse_args()

    by_item = collections.defaultdict(dict)  # (sid, model) -> {judge: record}
    for f in glob.glob(os.path.join(args.judgments, "*.json")):
        r = json.load(open(f, encoding="utf-8"))
        by_item[(r["scenario_id"], r["model"])][r["judge"]] = r

    # 评委一致性
    pairs, total_diffs = [], []
    for (sid, model), judges in by_item.items():
        names = sorted(judges)
        for i in range(len(names)):
            for k in range(i + 1, len(names)):
                a, b = judges[names[i]], judges[names[k]]
                fa, fb = flat_checklist(a["checklist"]), flat_checklist(b["checklist"])
                for key in set(fa) & set(fb):
                    pairs.append((fa[key], fb[key]))
                total_diffs.append(abs(a["score"]["total"] - b["score"]["total"]))
    kappa = cohen_kappa(pairs)

    # 每模型聚合（每题取各评委均值）
    per_model = collections.defaultdict(lambda: collections.defaultdict(list))
    item_scores = {}
    for (sid, model), judges in by_item.items():
        totals = [j["score"]["total"] for j in judges.values()]
        item_scores[(sid, model)] = round(statistics.mean(totals), 2)
        per_model[model]["total"].append(statistics.mean(totals))
        for d in DIMS:
            vals = [j["score"]["dims"][d] for j in judges.values() if j["score"]["dims"][d] is not None]
            if vals:
                per_model[model][d].append(statistics.mean(vals))
        per_model[model]["violations"].append(any(j["score"]["boundary_violated"] for j in judges.values()))

    summary = {}
    for model, d in per_model.items():
        row = {"n_items": len(d["total"]), "total": round(statistics.mean(d["total"]), 2),
               "total_ci": bootstrap_ci(d["total"]), "violations": sum(d["violations"])}
        for dim in DIMS:
            row[dim] = round(statistics.mean(d[dim]), 2) if d[dim] else None
        summary[model] = row

    # 与人工黄金集对照
    golden_stats = None
    if os.path.exists(args.golden):
        golden = yaml.safe_load(open(args.golden, encoding="utf-8"))
        diffs = []
        for sid, models in golden.items():
            for model, manual in models.items():
                if (sid, model) in item_scores:
                    diffs.append((sid, model, manual, item_scores[(sid, model)]))
        if diffs:
            mae = statistics.mean(abs(m - a) for _, _, m, a in diffs)
            within = sum(1 for _, _, m, a in diffs if abs(m - a) <= 0.5)
            golden_stats = {"n": len(diffs), "mae": round(mae, 2), "within_0.5": within,
                            "detail": [{"scenario": s, "model": mo, "manual": m, "auto": a} for s, mo, m, a in diffs]}

    out = {"items": len(by_item), "judge_pairs": len(total_diffs), "kappa_checklist": kappa,
           "judge_total_mad": round(statistics.mean(total_diffs), 2) if total_diffs else None,
           "models": summary, "golden": golden_stats}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump(out, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print("题×模型: %d ｜ 评委对: %d ｜ 清单 Kappa: %s ｜ 评委总分平均差: %s" % (
        out["items"], out["judge_pairs"], kappa, out["judge_total_mad"]))
    print("\n模型 | n | 总分 [95%CI] | 意图 | 发现 | 表态 | 闭环 | 越界")
    for model, r in sorted(summary.items(), key=lambda kv: -kv[1]["total"]):
        print("%s | %d | %.2f [%s, %s] | %s | %s | %s | %s | %d" % (
            model, r["n_items"], r["total"], r["total_ci"][0], r["total_ci"][1],
            r["intent"], r["discover"], r["stance"], r["ownership"], r["violations"]))
    if golden_stats:
        print("\n人工黄金集对照：n=%d，MAE=%.2f，偏差≤0.5 的 %d/%d" % (
            golden_stats["n"], golden_stats["mae"], golden_stats["within_0.5"], golden_stats["n"]))
        for d in golden_stats["detail"]:
            flag = "" if abs(d["manual"] - d["auto"]) <= 0.5 else "  ← 偏差"
            print("  %-12s %-18s 人工 %.1f  机评 %.2f%s" % (d["scenario"], d["model"], d["manual"], d["auto"], flag))


if __name__ == "__main__":
    main()
