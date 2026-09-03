#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 scenarios/L1/*.yaml 渲染成单页审题 HTML。用法：
collab-eval bank-page <输出路径>
"""
import collections, glob, html, os, sys
import yaml

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = sys.argv[1]
files = sorted(glob.glob(os.path.join(ROOT, "scenarios", "L1", "*.yaml")))
items = [yaml.safe_load(open(f, encoding="utf-8")) for f in files]
VCLASS = {"建议做": "v-do", "有条件做": "v-cond", "建议不做": "v-no"}
DOMAINS = ["PRD评审", "线上排障", "需求实现", "数据分析", "日常事务"]
by_dom = collections.defaultdict(list)
for it in items:
    by_dom[it["domain"]].append(it)

def esc(x): return html.escape(str(x).strip()) if x else ""
def pre(x): return '<pre class="material">%s</pre>' % esc(x) if x else ""

cards = []
for dom in DOMAINS:
    cards.append('<h2 id="%s">%s <span class="count">%d 题</span></h2>' % (dom, dom, len(by_dom[dom])))
    for s in by_dom[dom]:
        v = s["expected_stance"]["verdict"]
        chips = ['<span class="chip %s">%s</span>' % (VCLASS[v], v)]
        if s.get("type") == "paired":
            chips.append('<span class="chip c-pair">配对施压</span>')
        if (s.get("boundary") or {}).get("constraint"):
            chips.append('<span class="chip c-bound">含红线</span>')
        body = ['<details class="card %s"><summary><code>%s</code> %s</summary>' % (VCLASS[v], esc(s["id"]), "".join(chips))]
        if s.get("type") == "paired":
            body.append("<h4>中性版</h4>" + pre(s.get("prompt_neutral")))
            body.append("<h4>施压版</h4>" + pre(s.get("prompt_pressured")))
        else:
            body.append("<h4>用户提示</h4>" + pre(s.get("prompt")))
        body.append("<h4>真实意图</h4><p>%s</p>" % esc(s.get("true_intent")))
        body.append("<h4>埋点</h4><ul>")
        for p in s.get("planted_issues") or []:
            mm = "★必命中 " if p.get("must_mention") else ""
            body.append("<li><b>%s</b>（%s）%s%s<br><span class='ev'>证据：%s</span></li>" %
                        (esc(p.get("id")), esc(p.get("kind")), mm, esc(p.get("text")), esc(p.get("evidence"))))
        body.append("</ul>")
        body.append("<h4>正确立场</h4><p><b>%s</b> — 下一步：%s</p>" % (esc(v), esc(s["expected_stance"].get("next_step"))))
        ac = s.get("acceptable_clarification")
        if ac and str(ac).strip() not in ("~", "None"):
            body.append("<h4>可接受的反问</h4><p>%s</p>" % esc(ac))
        fu = s.get("follow_up_turns") or []
        if fu:
            body.append("<h4>追问轮</h4><ul>")
            for t in fu:
                body.append("<li>「%s」→ 期望：%s</li>" % (esc(t.get("user")), esc(t.get("expect"))))
            body.append("</ul>")
        b = s.get("boundary") or {}
        if b.get("constraint"):
            body.append("<h4>红线</h4><p>%s</p><ul>%s</ul>" % (esc(b["constraint"]),
                        "".join("<li>%s</li>" % esc(x) for x in b.get("violation_signals") or [])))
        a = s.get("anchors") or {}
        body.append("<h4>锚定样例</h4><table class='anchor'><tr><th>1分</th><td>%s</td></tr><tr><th>3分</th><td>%s</td></tr><tr><th>5分</th><td>%s</td></tr></table>" %
                    (esc(a.get("score_1")), esc(a.get("score_3")), esc(a.get("score_5"))))
        body.append("</details>")
        cards.append("".join(body))

stat = collections.Counter(s["expected_stance"]["verdict"] for s in items)
paired = sum(1 for s in items if s.get("type") == "paired")
bound = sum(1 for s in items if (s.get("boundary") or {}).get("constraint"))

TPL = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bank_template.html"), encoding="utf-8").read()
page = (TPL.replace("@N@", str(len(items)))
        .replace("@DO@", str(stat["建议做"]))
        .replace("@COND@", str(stat["有条件做"]))
        .replace("@NO@", str(stat["建议不做"]))
        .replace("@PAIR@", str(paired))
        .replace("@BOUND@", str(bound))
        .replace("@NAV@", "".join('<a href="#%s">%s</a>' % (d, d) for d in DOMAINS))
        .replace("@CARDS@", "\n".join(cards)))
open(OUT, "w", encoding="utf-8").write(page)
print("written", OUT, len(page))
