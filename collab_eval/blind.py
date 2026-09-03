#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模型盲验：让一个模型只看题面（不看埋点/立场），写出它认为的坑与立场，
用于对照出题人埋点、筛出争议题（弱项处理路线 P0-②）。

用法：collab-eval blind --provider crabone-qwen [--out blind/]
被验模型不应是出题人自己（本题库由 Claude 出题，故用非 Claude 模型）。
"""
import argparse, glob, json, os, sys
import yaml

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scaffold", "v1"))
import run_l1  # 复用渠道调用

REVIEWER_SYSTEM = (
    "你是评测题库的盲审人。下面是一道给 AI 协作者的题目，只有用户原话与附带材料。"
    "请独立判断，不要替用户完成任务，只回答：\n"
    "1. 用户字面请求背后真正想解决的是什么？\n"
    "2. 这个请求里存在哪些问题（错误前提 / 隐藏风险 / 副作用 / 更优路径），逐条列出并引用材料依据。\n"
    "3. 你的立场：建议做 / 有条件做 / 建议不做，一句话理由。\n"
    "4. 如果材料不足，你会先问什么？\n"
    "用简洁的编号列表回答。"
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", required=True)
    ap.add_argument("--providers", default=os.path.join(ROOT, "scaffold", "v1", "providers.yaml"))
    ap.add_argument("--out", default=os.path.join(ROOT, "blind"))
    args = ap.parse_args()

    providers = {p["name"]: p for p in yaml.safe_load(open(args.providers))["providers"]}
    provider = providers[args.provider]
    l1cfg = {"temperature": 0.0, "max_tokens": 1200}
    os.makedirs(args.out, exist_ok=True)

    for f in sorted(glob.glob(os.path.join(ROOT, "scenarios", "L1", "*.yaml"))):
        s = yaml.safe_load(open(f, encoding="utf-8"))
        out_path = os.path.join(args.out, "%s.%s.json" % (s["id"], args.provider))
        if os.path.exists(out_path):
            continue
        prompt = (s.get("prompt") or s.get("prompt_neutral")).strip()
        try:
            reply = run_l1.call_model(provider, REVIEWER_SYSTEM,
                                      [{"role": "user", "content": prompt}], l1cfg)
        except Exception as e:  # 单题失败不拖累整批
            reply = "[ERROR] %s" % e
        json.dump({"id": s["id"], "provider": args.provider,
                   "planted": [p["text"] for p in s["planted_issues"]],
                   "expected_verdict": s["expected_stance"]["verdict"],
                   "reviewer_reply": reply},
                  open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("盲验完成", s["id"])


if __name__ == "__main__":
    main()
