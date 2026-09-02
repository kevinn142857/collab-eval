#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盲验对照：把每份盲审回复与埋点比对（由一个核对模型判定每个坑是否被独立提到、立场是否一致），
汇总成争议题清单。用法：/usr/bin/python3 scripts/blind_compare.py --checker crabone-gpt56
"""
import argparse, collections, glob, json, os, sys, yaml
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scaffold", "v1"))
import run_l1

SYS = "你是核对员。判断一段独立评审意见是否提到了给定的每个要点，以及其立场。只输出 JSON。"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checker", required=True)
    ap.add_argument("--providers", default=os.path.join(ROOT, "scaffold", "v1", "providers.yaml"))
    args = ap.parse_args()
    providers = {p["name"]: p for p in yaml.safe_load(open(args.providers))["providers"]}
    out_dir = os.path.join(ROOT, "blind_compare"); os.makedirs(out_dir, exist_ok=True)
    rows = collections.defaultdict(dict)
    for f in sorted(glob.glob(os.path.join(ROOT, "blind", "*.json"))):
        b = json.load(open(f, encoding="utf-8"))
        if b["reviewer_reply"].startswith("[ERROR]"):
            continue
        out = os.path.join(out_dir, os.path.basename(f))
        if os.path.exists(out):
            r = json.load(open(out, encoding="utf-8"))
        else:
            prompt = ("要点列表（埋点）：\n" + "\n".join("P%d: %s" % (i + 1, t) for i, t in enumerate(b["planted"])) +
                      "\n\n评审意见：\n" + b["reviewer_reply"] +
                      "\n\n输出 JSON：{\"hits\": {\"P1\": true/false, ...}, \"verdict\": \"建议做|有条件做|建议不做|未表态\"}。"
                      "hits 的标准：评审意见明确把该点当作问题/风险/更优路径指出，才算 true。")
            raw = run_l1.call_model(providers[args.checker], SYS, [{"role": "user", "content": prompt}],
                                    {"temperature": 0.0, "max_tokens": 400})
            txt = raw[raw.find("{"):raw.rfind("}") + 1]
            r = json.loads(txt)
            json.dump(r, open(out, "w", encoding="utf-8"), ensure_ascii=False)
        rows[b["id"]][b["provider"]] = {"hits": r.get("hits", {}), "verdict": r.get("verdict"),
                                        "expected": b["expected_verdict"], "n": len(b["planted"])}
    # 汇总
    print("题 | 埋点数 | 坑被两方都命中 | 仅一方 | 都没中 | 立场(qwen/glm/埋点) | 判定")
    contested = []
    for sid in sorted(rows):
        revs = rows[sid]
        n = next(iter(revs.values()))["n"]
        both = one = none = 0
        for i in range(1, n + 1):
            hs = [bool(v["hits"].get("P%d" % i)) for v in revs.values()]
            if all(hs): both += 1
            elif any(hs): one += 1
            else: none += 1
        vs = [revs.get(k, {}).get("verdict", "-") for k in ("crabone-qwen", "crabone-glm")]
        exp = next(iter(revs.values()))["expected"]
        agree = sum(1 for v in vs if v == exp)
        flag = "保留" if (none == 0 and agree >= 1) else ("争议" if (none > 0 and agree == 0) else "复核")
        if flag != "保留": contested.append(sid)
        print("%s | %d | %d | %d | %d | %s/%s/%s | %s" % (sid, n, both, one, none, vs[0], vs[1], exp, flag))
    print("\n需复核/争议：", ", ".join(contested))

if __name__ == "__main__":
    main()
