#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自评（考生 = 本会话的 Claude 子代理）：出卷与收卷。

出卷：把每题的题面（不含任何埋点/答案）导成考卷 JSON，供主会话逐题派子代理作答。
  collab-eval selfeval sheet > /tmp/exam.json
收卷：把子代理的回答（answers.json：{conv_key: [reply1, reply2, ...]}）装配成 runner 同格式转录。
  collab-eval selfeval assemble --model claude-fable-5-1 --answers answers.json

考生隔离靠指令（不许读文件/用工具），报告须标注「子代理隔离，非物理隔离」。
"""
import argparse, datetime, glob, json, os, sys
import yaml

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SYSTEM_PROMPT = open(os.path.join(ROOT, "scaffold", "v1", "system_prompt.txt"), encoding="utf-8").read().strip()


def sheet():
    exam = {"system_prompt": SYSTEM_PROMPT, "items": []}
    for f in sorted(glob.glob(os.path.join(ROOT, "scenarios", "L1", "*.yaml"))):
        s = yaml.safe_load(open(f, encoding="utf-8"))
        fu = [t["user"] for t in (s.get("follow_up_turns") or [])]
        if s.get("type") == "paired":
            convs = {"prompt_neutral": [s["prompt_neutral"].strip()] + fu,
                     "prompt_pressured": [s["prompt_pressured"].strip()] + fu}
        else:
            convs = {"main": [s["prompt"].strip()] + fu}
        exam["items"].append({"id": s["id"], "conversations": convs})
    json.dump(exam, sys.stdout, ensure_ascii=False, indent=2)


def assemble(model, answers_path, out_root):
    answers = json.load(open(answers_path, encoding="utf-8"))  # {sid: {conv_key: [replies]}}
    exam = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "scenarios", "L1", "*.yaml"))):
        s = yaml.safe_load(open(f, encoding="utf-8"))
        exam[s["id"]] = s
    ts = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    n = 0
    for sid, convs in answers.items():
        s = exam[sid]
        fu = [t["user"] for t in (s.get("follow_up_turns") or [])]
        record = {"scaffold_version": "v1", "provider": {"name": model, "model": model, "api": "subagent"},
                  "temperature": None, "timestamp": ts, "scenario_id": sid, "sample": 1, "conversations": {}}
        for key, replies in convs.items():
            first = s["prompt"] if key == "main" else s[key]
            users = [first.strip()] + fu
            record["conversations"][key] = [{"user": u, "assistant": a} for u, a in zip(users, replies)]
        d = os.path.join(out_root, sid, model)
        os.makedirs(d, exist_ok=True)
        json.dump(record, open(os.path.join(d, "%s-sample1.json" % ts), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        n += 1
    print("装配 %d 份转录 → %s/*/%s" % (n, out_root, model))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["sheet", "assemble"])
    ap.add_argument("--model", default="claude-fable-5-1")
    ap.add_argument("--answers")
    ap.add_argument("--out", default=os.path.join(ROOT, "transcripts"))
    a = ap.parse_args()
    if a.cmd == "sheet":
        sheet()
    else:
        assemble(a.model, a.answers, a.out)
