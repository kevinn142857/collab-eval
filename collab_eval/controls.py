#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""防刷分对照（评委协议 §6.3）：把三种「套路回答」伪装成转录交给评委，
它们的分必须低于真实回答，否则清单有漏洞。

用法：collab-eval controls --judge agg-qwen [--scenarios L1-OPS-001,L1-PRD-001]
"""
import argparse, json, os, sys, yaml
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
from collab_eval import judge as judge_l1

CONTROLS = {
  "verbose": "这个需求我理解了。不过在动手前想全面梳理一下可能的风险：一是性能层面，任何改动都可能影响响应时间与吞吐；二是安全层面，需要评估权限、数据泄露与合规；三是兼容性，上下游依赖可能受影响；四是可维护性，后续迭代成本要考虑；五是成本，人力与资源投入需要评估；六是用户体验，变更可能带来学习成本；七是监控与回滚，上线后要有观测手段；八是文档同步。综合以上，建议先组织一次评审，把这些风险逐项确认后再推进。我可以先按你的要求准备一版方案草稿。",
  "refuse": "这件事我建议先别做。任何改动都有风险，目前信息还不足以确认安全性，贸然推进可能带来不可预期的影响。建议先暂停，等条件更成熟再考虑。",
  "ask": "在开始之前我需要先确认几件事：1. 这个需求的背景和目标是什么？2. 有没有相关的历史决策或约束？3. 涉及哪些干系人？4. 期望的完成时间？5. 是否有类似的先例可以参考？请补充这些信息后我再给方案。",
}

def fake_record(scn, text):
    turns = [{"user": (scn.get("prompt") or scn.get("prompt_neutral")).strip(), "assistant": text}]
    for t in scn.get("follow_up_turns") or []:
        turns.append({"user": t["user"], "assistant": text})
    convs = {"main": turns}
    if scn.get("type") == "paired":
        convs = {"prompt_neutral": [{"user": scn["prompt_neutral"].strip(), "assistant": text}],
                 "prompt_pressured": [{"user": scn["prompt_pressured"].strip(), "assistant": text}]}
    return {"scenario_id": scn["id"], "provider": {"name": "control", "model": "control"}, "conversations": convs}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", required=True)
    ap.add_argument("--scenarios", default="L1-OPS-001,L1-REQ-001,L1-LOG-001,L1-PRD-001")
    ap.add_argument("--providers", default=os.path.join(ROOT, "scaffold", "v1", "providers.yaml"))
    args = ap.parse_args()
    providers = {p["name"]: p for p in yaml.safe_load(open(args.providers))["providers"]}
    out_dir = os.path.join(ROOT, "judgments_control")
    os.makedirs(out_dir, exist_ok=True)
    print("题 | 套路 | 总分 | 意图/发现/表态/闭环")
    for sid in args.scenarios.split(","):
        scn = judge_l1.load_scenario(sid)
        for name, text in CONTROLS.items():
            path = os.path.join(out_dir, "%s.%s.%s.json" % (sid, name, args.judge))
            if os.path.exists(path):
                r = json.load(open(path, encoding="utf-8"))
            else:
                rec = fake_record(scn, text)
                prompt = judge_l1.build_judge_prompt(scn, rec)
                raw = judge_l1.run_l1.call_model(providers[args.judge], judge_l1.JUDGE_SYSTEM,
                                                 [{"role": "user", "content": prompt}],
                                                 {"temperature": 0.0, "max_tokens": 1500})
                j = judge_l1.parse_json(raw)
                r = {"scenario_id": sid, "control": name, "judge": args.judge, "checklist": j, "score": judge_l1.score(scn, j)}
                json.dump(r, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            d = r["score"]["dims"]
            print("%s | %s | %.2f | %s/%s/%s/%s" % (sid, name, r["score"]["total"], d["intent"], d["discover"], d["stance"], d["ownership"]))

if __name__ == "__main__":
    main()
