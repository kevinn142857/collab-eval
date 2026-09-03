#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""结果页：从 judgments/ + results/results.json（+ judgments_control/）渲染单页 HTML。
用法：collab-eval report <out.html>
原则：五维分开展示、带置信区间、区间重叠标「不可区分」、不合成排名名次。
"""
import collections, glob, html, json, os, statistics, sys
import yaml

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DIMS = [("intent", "意图"), ("discover", "发现"), ("stance", "表态"), ("ownership", "闭环")]
MODEL_LABEL = {}


def esc(x):
    return html.escape(str(x)) if x is not None else ""


def load():
    results = json.load(open(os.path.join(ROOT, "results", "results.json"), encoding="utf-8"))
    judgments = collections.defaultdict(dict)   # (sid, model) -> {judge: rec}
    for f in glob.glob(os.path.join(ROOT, "judgments", "*.json")):
        r = json.load(open(f, encoding="utf-8"))
        judgments[(r["scenario_id"], r["model"])][r["judge"]] = r
        MODEL_LABEL[r["model"]] = r.get("model_id") or r["model"]
    controls = [json.load(open(f, encoding="utf-8")) for f in glob.glob(os.path.join(ROOT, "judgments_control", "*.json"))]
    scenarios = {}
    for f in glob.glob(os.path.join(ROOT, "scenarios", "L1", "*.yaml")):
        s = yaml.safe_load(open(f, encoding="utf-8"))
        scenarios[s["id"]] = s
    return results, judgments, controls, scenarios


def score_cell(v):
    if v is None:
        return '<td class="na">—</td>'
    pct = (v - 1) / 4 * 100
    return '<td><span class="bar" style="--w:%.0f%%"></span>%.2f</td>' % (pct, v)


def render(out_path):
    results, judgments, controls, scenarios = load()
    models = results["models"]
    order = sorted(models, key=lambda m: -models[m]["total"])
    sids = sorted({sid for sid, _ in judgments})

    # 不可区分判定：任意两模型 CI 重叠
    cis = {m: models[m]["total_ci"] for m in order}
    overlaps = all(cis[a][1] >= cis[b][0] for i, a in enumerate(order) for b in order[i + 1:] if cis[a][0] is not None and cis[b][0] is not None)

    parts = []
    parts.append('<h1>「做好」评测结果</h1>')
    parts.append('<p class="sub">参考脚手架 v1 · 题库 v1（%d 题，本页覆盖 %d 题）· 双评委清单核对 · 生成于 %s</p>' % (
        len(scenarios), len(sids), results.get("generated", "")))
    parts.append('<div class="stats"><span>模型 %d</span><span>题×模型 %d</span><span>评委对 %d</span><span>清单 Kappa %s</span><span>评委总分平均差 %s</span></div>' % (
        len(models), results["items"], results["judge_pairs"], results["kappa_checklist"], results["judge_total_mad"]))
    if overlaps:
        parts.append('<div class="notice">所有模型的总分 95%% 置信区间相互重叠：按榜单规则，本页<b>不构成排名</b>。样本 %d 题只够发现大差距；下方顺序仅按均值排列以便阅读。</div>' % len(sids))
    parts.append('<div class="notice muted">全部成绩经同一聚合渠道取得（模型 @ crabone），含渠道层因素；信任级别：Official（内部执行）。评委：跨厂商分配 + 仲裁，评委只核对清单不打分。</div>')

    # 榜单
    parts.append('<h2>五维总览</h2><div class="scroll"><table class="board"><tr><th>模型</th><th>n</th><th>总分 [95% CI]</th>' +
                 "".join("<th>%s</th>" % cn for _, cn in DIMS) + '<th>越界</th><th>评委数</th></tr>')
    for m in order:
        r = models[m]
        ci = r["total_ci"]
        judges = sorted({j for (sid, mm), js in judgments.items() if mm == m for j in js})
        parts.append('<tr><td class="model">%s<br><span class="muted small">@%s</span></td><td>%d</td><td><b>%.2f</b> <span class="muted">[%s, %s]</span></td>' % (
            esc(MODEL_LABEL.get(m, m)), esc(m.split("-")[0]), r["n_items"], r["total"], ci[0], ci[1]))
        for d, _ in DIMS:
            parts.append(score_cell(r.get(d)))
        parts.append('<td>%s</td><td>%d</td></tr>' % ("⚠ %d" % r["violations"] if r["violations"] else "0", len(judges)))
    parts.append('</table></div>')

    # 题×模型矩阵
    parts.append('<h2>题 × 模型（各评委均分）</h2><div class="scroll"><table class="matrix"><tr><th>题</th>' +
                 "".join('<th>%s</th>' % esc(MODEL_LABEL.get(m, m)) for m in order) + '</tr>')
    for sid in sids:
        s = scenarios.get(sid, {})
        parts.append('<tr><td class="model"><code>%s</code><br><span class="muted small">%s · %s</span></td>' % (
            sid, esc(s.get("domain", "")), esc((s.get("expected_stance") or {}).get("verdict", ""))))
        for m in order:
            js = judgments.get((sid, m))
            if not js:
                parts.append('<td class="na">—</td>')
                continue
            tot = statistics.mean(j["score"]["total"] for j in js.values())
            viol = any(j["score"]["boundary_violated"] for j in js.values())
            parts.append('<td class="s%d">%.1f%s</td>' % (round(tot), tot, " ⚠" if viol else ""))
        parts.append('</tr>')
    parts.append('</table></div>')

    # 明细
    parts.append('<h2>逐题明细与原文证据</h2>')
    for sid in sids:
        s = scenarios.get(sid, {})
        planted = [p["id"] for p in (s.get("planted_issues") or [])]
        parts.append('<details class="card"><summary><code>%s</code> %s · 期望立场：%s · 埋点：%s</summary>' % (
            sid, esc(s.get("domain", "")), esc((s.get("expected_stance") or {}).get("verdict", "")), ", ".join(planted)))
        parts.append('<div class="scroll"><table class="detail"><tr><th>模型</th><th>总分</th><th>命中</th><th>立场</th><th>评委</th><th>表态依据（评委引用）</th></tr>')
        for m in order:
            js = judgments.get((sid, m))
            if not js:
                continue
            for jn, j in sorted(js.items()):
                c, sc = j["checklist"], j["score"]
                hits = " ".join("%s%s" % (p, "✓" if sc["planted_hits"].get(p) else "✗") for p in planted)
                if s.get("type") == "paired":
                    stance = "%s → %s%s" % (esc(c.get("verdict_neutral")), esc(c.get("verdict_pressured")),
                                            "" if c.get("paired_consistent") else " <b class='bad'>改口</b>")
                else:
                    stance = esc(c.get("verdict"))
                quote = (c.get("quotes") or {}).get("Q5", "")
                parts.append('<tr><td class="model">%s</td><td class="s%d">%.2f%s</td><td>%s</td><td>%s</td><td class="small muted">%s</td><td class="quote">%s</td></tr>' % (
                    esc(MODEL_LABEL.get(m, m)), round(sc["total"]), sc["total"], " ⚠" if sc["boundary_violated"] else "",
                    hits, stance, esc(j.get("judge_model") or jn), esc(str(quote)[:220])))
        parts.append('</table></div></details>')

    # 套路对照
    if controls:
        parts.append('<h2>防刷分对照</h2><p class="muted">三种套路回答（冗长堆风险 / 一律先别做 / 一律先反问）伪装成转录送评，应显著低于真实回答。</p>')
        parts.append('<div class="scroll"><table class="board"><tr><th>题</th><th>套路</th><th>评委</th><th>总分</th>' + "".join("<th>%s</th>" % cn for _, cn in DIMS) + '</tr>')
        for r in sorted(controls, key=lambda r: (r["scenario_id"], r["control"], r["judge"])):
            parts.append('<tr><td><code>%s</code></td><td>%s</td><td class="small muted">%s</td><td><b>%.2f</b></td>' % (
                r["scenario_id"], r["control"], esc(r["judge"]), r["score"]["total"]) +
                "".join(score_cell(r["score"]["dims"].get(d)) for d, _ in DIMS) + '</tr>')
        parts.append('</table></div>')

    # 黄金集
    g = results.get("golden")
    if g:
        parts.append('<h2>与人工黄金集对照</h2><p>n=%d，MAE=%.2f，偏差 ≤0.5 的 %d/%d。<span class="muted">当前黄金集为 2026-08 单评委印象分，已判定不合格，待按清单重建。</span></p>' % (
            g["n"], g["mae"], g["within_0.5"], g["n"]))

    tpl = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "report_template.html"), encoding="utf-8").read()
    page = tpl.replace("@BODY@", "\n".join(parts))
    open(out_path, "w", encoding="utf-8").write(page)
    print("written", out_path, len(page))


if __name__ == "__main__":
    render(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "results", "index.html"))
