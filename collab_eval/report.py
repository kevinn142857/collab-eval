#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""结果页（榜单式）：从 judgments/ + results/results.json（+ judgments_control/）渲染单页应用。
用法：collab-eval report <out.html>
参考主流榜单骨架（Arena / Artificial Analysis / Epoch / HAL）：维度 tab、列排序、筛选、
分数 ± CI 与名次区间、机构标识、不完整数据标灰、行内展开逐题 trace、方法/提交/更新页尾。
原则不变：区间重叠即不构成排名；不合成单一名次；评委只核对不打分。
"""
import collections, glob, json, os, statistics, sys
import yaml

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DIMS = [("intent", "意图"), ("discover", "发现"), ("stance", "表态"), ("ownership", "闭环")]
ORG = [("gpt", "OpenAI"), ("claude", "Anthropic"), ("deepseek", "DeepSeek"), ("glm", "智谱"),
       ("minimax", "MiniMax"), ("qwen", "阿里"), ("doubao", "字节"), ("gemini", "Google")]


def org_of(model_id):
    m = (model_id or "").lower()
    for k, v in ORG:
        if k in m:
            return v
    return "—"


def load():
    results = json.load(open(os.path.join(ROOT, "results", "results.json"), encoding="utf-8"))
    judgments = collections.defaultdict(dict)
    labels = {}
    for f in glob.glob(os.path.join(ROOT, "judgments", "*.json")):
        r = json.load(open(f, encoding="utf-8"))
        judgments[(r["scenario_id"], r["model"])][r["judge"]] = r
        labels[r["model"]] = r.get("model_id") or r["model"]
    controls = [json.load(open(f, encoding="utf-8")) for f in glob.glob(os.path.join(ROOT, "judgments_control", "*.json"))]
    scenarios = {}
    for f in glob.glob(os.path.join(ROOT, "scenarios", "L1", "*.yaml")):
        s = yaml.safe_load(open(f, encoding="utf-8"))
        scenarios[s["id"]] = s
    return results, judgments, controls, scenarios, labels


def mean_or_none(vals):
    vals = [v for v in vals if v is not None]
    return round(statistics.mean(vals), 2) if vals else None


def build_data(results, judgments, controls, scenarios, labels):
    sids = sorted({sid for sid, _ in judgments})
    max_n = max(results["models"][m]["n_items"] for m in results["models"])
    models = []
    for m, r in results["models"].items():
        items = []
        for sid in sids:
            js = judgments.get((sid, m))
            if not js:
                continue
            s = scenarios.get(sid, {})
            planted = [p["id"] for p in (s.get("planted_issues") or [])]
            per_judge = []
            for jn, j in sorted(js.items()):
                c, sc = j["checklist"], j["score"]
                if s.get("type") == "paired":
                    stance = "%s → %s" % (c.get("verdict_neutral"), c.get("verdict_pressured"))
                else:
                    stance = c.get("verdict")
                per_judge.append({"judge": j.get("judge_model") or jn, "total": sc["total"], "dims": sc["dims"],
                                  "hits": [bool(sc["planted_hits"].get(p)) for p in planted],
                                  "stance": stance, "flipped": bool(sc.get("stance_flipped")),
                                  "violated": bool(sc["boundary_violated"]),
                                  "quote": str((c.get("quotes") or {}).get("Q5", ""))[:240]})
            items.append({"sid": sid, "domain": s.get("domain", ""),
                          "expected": (s.get("expected_stance") or {}).get("verdict", ""),
                          "planted": planted, "paired": s.get("type") == "paired",
                          "total": round(statistics.mean(x["total"] for x in per_judge), 2),
                          "dims": {d: mean_or_none([x["dims"][d] for x in per_judge]) for d, _ in DIMS},
                          "flipped": any(x["flipped"] for x in per_judge),
                          "violated": any(x["violated"] for x in per_judge),
                          "judges": per_judge})
        models.append({"id": m, "label": labels.get(m, m), "org": org_of(labels.get(m, m)),
                       "channel": m.split("-")[0], "n": r["n_items"], "complete": r["n_items"] == max_n,
                       "total": r["total"], "ci": r["total_ci"], "dims": {d: r.get(d) for d, _ in DIMS},
                       "violations": r["violations"], "flips": r.get("flips", 0),
                       "judges": sorted({x["judge"] for it in items for x in it["judges"]}), "items": items})
    questions = [{"sid": sid, "domain": scenarios.get(sid, {}).get("domain", ""),
                  "expected": (scenarios.get(sid, {}).get("expected_stance") or {}).get("verdict", ""),
                  "paired": scenarios.get(sid, {}).get("type") == "paired"} for sid in sids]
    ctrl = [{"sid": r["scenario_id"], "control": r["control"], "judge": r["judge"],
             "total": r["score"]["total"], "dims": r["score"]["dims"]}
            for r in sorted(controls, key=lambda r: (r["scenario_id"], r["control"], r["judge"]))]
    meta = {"generated": results.get("generated", ""), "items": results["items"], "pairs": results["judge_pairs"],
            "kappa": results["kappa_checklist"], "mad": results["judge_total_mad"], "bank_size": len(scenarios),
            "covered": len(sids), "golden": results.get("golden")}
    return {"meta": meta, "models": models, "questions": questions, "controls": ctrl, "dims": DIMS}


def render(out_path):
    data = build_data(*load())
    tpl = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "report_template.html"), encoding="utf-8").read()
    page = tpl.replace("@DATA@", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    open(out_path, "w", encoding="utf-8").write(page)
    print("written", out_path, len(page))


if __name__ == "__main__":
    render(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "results", "index.html"))
