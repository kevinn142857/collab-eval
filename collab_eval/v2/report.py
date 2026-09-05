"""Self-contained, escaped evidence reports with accessible local filtering."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from .schema import Json

LABELS = {
    "pass": "通过",
    "fail": "未通过",
    "unresolved": "未决",
    "not_applicable": "不适用",
}
CONDITIONS = {
    "baseline": "正常请求",
    "pressure": "无新信息施压",
    "evidence_update": "新增证据",
    "authorization": "授权变化",
}


def e(value: Any) -> str:
    return escape(str(value), quote=True)


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def rate(low: float, high: float) -> str:
    return pct(low) if abs(low - high) < 1e-9 else f"{pct(low)}–{pct(high)}"


def bar(low: float, high: float) -> str:
    return f'<div class="track" aria-hidden="true"><i style="width:{high * 100:.4f}%"></i><b style="width:{low * 100:.4f}%"></b></div>'


def trace_html(row: Json, titles: dict[str, str]) -> str:
    trace = row.get("trace", {})
    turns = "".join(
        f'<div class="turn"><small>第 {i} 轮 · 用户</small><pre>{e(t["user"])}</pre><small>回答</small><pre>{e(t["assistant"])}</pre></div>'
        for i, t in enumerate(trace.get("turns", []), 1)
    )
    if not turns:
        turns = '<p class="muted">此试验尚未运行，仍计入计划分母。</p>'
    checks = "".join(
        f'<tr><td>{e(c["description"])}</td><td><span class="state {e(c["status"])}">{LABELS[c["status"]]}</span></td><td>{"人工裁决" if c["adjudicated"] else " / ".join(LABELS.get(s, s) for s in c["judge_states"]) or "待判定"}</td></tr>'
        for c in row["checks"]
    )
    judgments: list[str] = []
    for j in row.get("judgments", []):
        refs = []
        for check in j.get("checks", []):
            citations = "；".join(
                f"第 {e(r['turn'])} 轮：{e(r['quote'])}" for r in check["citations"]
            )
            refs.append(
                f"<li><b>{e(check['criterion_id'])}</b> · {e(LABELS.get(check['status'], check['status']))}<p>{e(check['reason'])}</p><blockquote>{citations or '无引用 / 不适用'}</blockquote></li>"
            )
        judgments.append(
            f'<details class="judge"><summary>{e(j["judge_id"])} · {e(j["parse_status"])}</summary><ul>{"".join(refs)}</ul><details><summary>原始评委响应</summary><pre>{e(j.get("raw", ""))}</pre></details></details>'
        )
    decisions = "".join(
        f'<article class="judge"><h4>人工裁决 · {e(LABELS[d["status"]])}</h4><p><b>{e(d["reviewer"])}</b> · {e(d["criterion_id"])} · {e(d["reason"])}</p>'
        + "".join(
            f"<blockquote>第 {e(ref['turn'])} 轮：{e(ref['quote'])}</blockquote>"
            for ref in d["citations"]
        )
        + "</article>"
        for d in row.get("adjudications", [])
    )
    condition = row["condition"]
    standards = "".join(f"<li>{e(a)}</li>" for a in condition["acceptable_answers"])
    return f'''<details class="case" data-domain="{e(row["domain"])}" data-status="{e(row["status"])}" id="trial-{e(row["trial_id"])}">
    <summary><span class="case-name">{e(titles[row["family_id"]])}<small>{e(row["domain"])} / {CONDITIONS[row["condition_id"]]} / 第 {row["sample"]} 次</small></span><span class="state {e(row["status"])}">{LABELS[row["status"]]}</span><span class="expand">＋</span></summary>
    <div class="case-body"><p class="mono">试验 {e(row["trial_id"])} · 运行状态 {e(trace.get("status", "not_run"))}</p>
    <div class="evidence-grid"><section><h3>原始对话</h3>{turns}</section><section><h3>判定依据</h3><div class="scroll"><table><thead><tr><th>标准</th><th>结论</th><th>来源</th></tr></thead><tbody>{checks}</tbody></table></div><details><summary>可接受答案示例（不限定措辞）</summary><ul>{standards}</ul></details>{"".join(judgments)}{decisions}</section></div></div></details>'''


def render(report: Json, output: Path, comparison: Json | None = None) -> None:
    """Render untrusted transcript text as text, never executable HTML."""
    m, s = report["manifest"], report["summary"]
    titles = {f["id"]: f["title"] for f in m["families"]}
    simulated = m["mode"] == "synthetic"
    domain_options = "".join(f"<option>{e(d['domain'])}</option>" for d in report["domains"])
    domain_rows = "".join(
        f"<tr><td>{e(d['domain'])}</td><td>{rate(d['rate_lower'], d['rate_upper'])}{bar(d['rate_lower'], d['rate_upper'])}</td><td>{d['families']} 族 / {d['expected']} 次</td><td>{rate(*d['ci']) if d['ci'] else '独立任务不足'}</td></tr>"
        for d in report["domains"]
    )
    metrics = []
    for key, label, positive in [
        ("boundary", "重大边界事件", False),
        ("friction", "无依据阻拦", False),
        ("update", "证据更新", True),
        ("repair", "有错后的修复", True),
    ]:
        value = report["metrics"][key]
        n = value["opportunities"]
        count = value["pass" if positive else "fail"]
        number = f"{count}<small> / {n}</small>" if n else "—"
        note = f"{value['unresolved']} 次未决" if n else "本批无适用机会"
        metrics.append(
            f'<article><h3>{label}</h3><div class="metric-number">{number}</div><p>{note}</p></article>'
        )
    pressure = report["metrics"]["pressure"]
    if comparison:
        names = {
            "incomparable": "不可比较",
            "insufficient_evidence": "证据不足",
            "improved": "有实质改善证据",
            "regressed": "有实质退步证据",
            "equivalent_within_margin": "差异落在预定等效范围",
        }
        delta = comparison.get("difference_bounds")
        detail = (
            f"{delta[0] * 100:+.1f} 至 {delta[1] * 100:+.1f} 个百分点" if delta else "不计算差值"
        )
        comp = f'<div class="comparison"><div><small>{e(comparison["b"])} − {e(comparison["a"])}</small><h3>{detail}</h3></div><span class="state unresolved">{names[comparison["status"]]}</span></div><p>{e(comparison["reason"])}</p>'
        interval = comparison.get("ci")
        comp += f"<p>配对 95% 区间：{e(interval) if interval else '独立任务不足'}；实用差异阈值：{comparison['margin'] * 100:.1f} 个百分点。</p>"
    else:
        comp = '<p>选择两份冻结运行，用同一任务集做配对比较。版本或评委不同会明确标为不可比较。</p><pre class="command">python -m collab_eval.cli v2 compare --a RUN_A --b RUN_B --out comparison.html</pre>'
    interval = rate(*s["ci"]) if s["ci"] else "独立任务不足，暂不估计"
    status = "离线模拟 · 非真实成绩" if simulated else "本地运行 · 结果待复核"
    tokens = {
        "TITLE": e(m["config"]["name"]),
        "STATUS": status,
        "NOTICE": "本页使用构造的演示转录与模拟判定，只展示产品流程，不代表任何模型表现。"
        if simulated
        else "结果属于本次配置与任务集。未决结果保留在分母中，评委尚未通过独立校准。",
        "RATE": rate(s["rate_lower"], s["rate_upper"]),
        "BAR": bar(s["rate_lower"], s["rate_upper"]),
        "INTERVAL": interval,
        "PASS": str(s["pass"]),
        "FAIL": str(s["fail"]),
        "UNRESOLVED": str(s["unresolved"]),
        "FAMILIES": str(s["families"]),
        "EXPECTED": str(s["expected"]),
        "METRICS": "".join(metrics),
        "DOMAINS": domain_rows,
        "OPTIONS": domain_options,
        "CASES": "".join(
            trace_html(r, titles)
            for r in sorted(
                report["trials"],
                key=lambda r: (r["family_id"], r["condition_id"], r["sample"]),
            )
        ),
        "COMPARISON": comp,
        "CONFIG": e(json_config(m)),
        "RUNID": e(m["run_id"]),
        "CREATED": e(m["created"][:16].replace("T", " ") + " UTC"),
        "BANKSTATUS": e(report["provenance"]["bank"]),
        "PRESSURE": f"{pressure['harmful']} / {pressure['baseline_pass']}",
        "PRESSURE_NOTE": f"共 {pressure['pairs']} 组配对；基准通过 {pressure['baseline_pass']} 组，其中压力条件未决 {pressure['unresolved']} 组。",
    }
    template = Path(__file__).with_name("report_template.html").read_text(encoding="utf-8")
    # Single substitution pass prevents user text resembling a placeholder from
    # being interpreted as another template instruction.
    import re

    page = re.sub(r"@@([A-Z_]+)@@", lambda match: tokens[match[1]], template)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")


def json_config(manifest: Json) -> str:
    """Expose declared nonsecret configuration and measurement scope."""
    import json

    return json.dumps(
        {
            "config": manifest["config"],
            "samples_per_condition": manifest["samples"],
            "max_calls": manifest["max_calls"],
            "scorer_version": manifest["scorer_version"],
            "mode": manifest["mode"],
        },
        ensure_ascii=False,
        indent=2,
    )
