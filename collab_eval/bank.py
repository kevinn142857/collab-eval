#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L1 题库校验：入库前跑一次（评测框架设计 §3.5 的硬约束）。

用法：collab-eval validate
"""
import collections
import re
import glob
import os
import sys

import yaml

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
VERDICTS = ("建议做", "有条件做", "建议不做")

errors, stances, domains = [], collections.Counter(), collections.Counter()
paired = boundary = 0
files = sorted(glob.glob(os.path.join(ROOT, "scenarios", "L1", "*.yaml")))

for f in files:
    sid = os.path.basename(f)
    s = yaml.safe_load(open(f, encoding="utf-8"))
    def err(msg):
        errors.append("%s: %s" % (sid, msg))

    for field in ("id", "domain", "true_intent", "planted_issues", "expected_stance", "anchors"):
        if not s.get(field):
            err("缺字段 %s" % field)
    if s.get("type") == "paired":
        paired += 1
        if not (s.get("prompt_neutral") and s.get("prompt_pressured")):
            err("paired 题缺 prompt_neutral/prompt_pressured")
    elif not s.get("prompt"):
        err("缺 prompt")

    v = (s.get("expected_stance") or {}).get("verdict")
    if v not in VERDICTS:
        err("verdict 非法: %r" % v)
    else:
        stances[v] += 1
    domains[s.get("domain", "?")] += 1

    b = s.get("boundary") or {}
    if b.get("constraint"):
        boundary += 1

    prompt_text = s.get("prompt") or (s.get("prompt_neutral", "") + s.get("prompt_pressured", ""))
    for p in s.get("planted_issues") or []:
        ev = p.get("evidence")
        if not ev:
            err("坑 %s 缺 evidence" % p.get("id"))
            continue
        annotated = ("随题附带" in str(ev)) or ("评委侧" in str(ev))
        if not annotated:
            err("坑 %s 的 evidence 未标注「随题附带/评委侧」" % p.get("id"))
        if p.get("must_mention") and "随题附带" not in str(ev):
            err("must_mention 坑 %s 的证据未随题附带（模型无发现途径）" % p.get("id"))
        if p.get("must_mention") and not re.search(r"附[^\n，。]{0,12}[:：]", prompt_text):
            err("must_mention 坑 %s：prompt 中未见附带材料段" % p.get("id"))
    a = s.get("anchors") or {}
    for k in ("score_1", "score_3", "score_5"):
        if not a.get(k):
            err("缺锚定 %s" % k)

n = len(files)
print("题目数: %d" % n)
print("领域分布: %s" % dict(domains))
print("立场分布: %s" % dict(stances))
print("配对施压: %d（要求 ≥ %d）" % (paired, n // 3))
print("含红线: %d（要求 ≥ %d）" % (boundary, n // 3))

target = n / 3
for v in VERDICTS:
    if abs(stances[v] - target) > 5:
        errors.append("立场配比失衡: %s = %d（目标 %.0f ± 5）" % (v, stances[v], target))
if paired < n // 3:
    errors.append("配对施压题不足")
if boundary < n // 3:
    errors.append("含红线题不足")

if errors:
    print("\n未通过（%d 项）:" % len(errors))
    for e in errors:
        print("  -", e)
    sys.exit(1)
print("\n校验通过")
