"""Build a local, evidence-linked table from verified v2 run directories."""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import quote

from .judging import collect
from .report import e, rate, render
from .schema import Json, digest, require, write_json


def build(paths: list[Path], output: Path) -> Json:
    """Recompute sealed evidence; keep missing trials and reviews in the denominator."""
    require(bool(paths), "at least one run is required")
    reports = [collect(path) for path in paths]
    require(all(r["manifest"]["mode"] == "live" for r in reports), "live runs only")
    require(
        len({digest(r["manifest"]["families"]) for r in reports}) == 1,
        "leaderboard requires identical task snapshots",
    )
    require(output.suffix == ".html", "output must be HTML")
    output.parent.mkdir(parents=True, exist_ok=True)
    # A dedicated export directory keeps generated files away from sealed input records.
    for path in paths:
        require(not output.parent.resolve().is_relative_to(path.resolve()), "export outside runs")
    rows = []
    domains: dict[str, list[str]] = {}
    reports.sort(key=lambda r: (-r["summary"]["rate_lower"], r["manifest"]["config"]["model"]))
    for i, report in enumerate(reports):
        model = report["manifest"]["config"]["model"]
        s = report["summary"]
        detail = f"model-{i + 1}.html"
        render(report, output.parent / detail)
        write_json(output.parent / f"model-{i + 1}.json", report)
        states: dict[str, int] = {}
        for trial in report["trials"]:
            state = trial["trace"]["status"]
            states[state] = states.get(state, 0) + 1
        completed = states.get("complete", 0)
        run_note = f"完整回答 {completed}；未完成 {s['expected'] - completed}"
        display_rate = (
            rate(s["rate_lower"], s["rate_upper"]) if s["pass"] + s["fail"] else "证据不足"
        )
        rows.append(
            f'<tr><td><a href="{quote(detail)}">{e(model)} ↗</a><small>{e(report["manifest"]["config"]["base_url"])}</small></td>'
            f"<td><strong>{display_rate}</strong></td>"
            f"<td>{s['pass']} / {s['fail']} / {s['unresolved']}</td>"
            f"<td>{rate(*s['ci']) if s['ci'] else '样本不足'}</td>"
            f"<td>{s['families']} / {s['expected']}<small>{e(run_note)}</small></td></tr>"
        )
        for domain in report["domains"]:
            domains.setdefault(domain["domain"], []).append(
                f"<td>{rate(domain['rate_lower'], domain['rate_upper'])}</td>"
            )
    headings = "".join(f"<th>{e(r['manifest']['config']['model'])}</th>" for r in reports)
    breakdown = "".join(f"<tr><th>{e(d)}</th>{''.join(cells)}</tr>" for d, cells in domains.items())
    calls = sum(r["usage"]["candidate_calls"] + r["usage"]["judge_calls"] for r in reports)
    page = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>做好 · v2 真实试测榜</title><style>
:root{{color-scheme:light}}*{{box-sizing:border-box}}body{{margin:0;background:#f6f5ee;color:#23382f;font:16px/1.65 "PingFang SC",sans-serif}}main{{max-width:1240px;margin:auto;padding:32px 28px 80px}}nav{{display:flex;justify-content:space-between;border-bottom:1px solid #cbd3c8;padding-bottom:18px}}h1{{font:500 clamp(36px,6vw,68px)/1.2 "Songti SC",serif;margin:38px 0 18px}}h2{{margin-top:44px;font-weight:500}}a{{color:inherit}}small{{display:block;font-size:12px;color:#6b786f;max-width:280px;overflow-wrap:anywhere}}.note{{border-left:3px solid #6c806b;padding:14px 20px;background:#e9eee3;margin:24px 0}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%;white-space:nowrap}}th,td{{text-align:left;padding:22px 16px;border-bottom:1px solid #cbd3c8}}th{{font-size:13px;color:#637362}}td strong{{font-size:23px;font-weight:500}}td:first-child{{font-weight:600}}footer{{margin-top:40px;color:#637362}}@media(max-width:600px){{main{{padding:24px 16px}}th,td{{padding:16px 12px}}}}
</style><main><nav><b>做好 / COLLAB EVAL</b><span>V2 · LIVE PILOT</span></nav>
<h1>协作表现，回到证据。</h1><p>{len(reports)} 个模型配置 · {calls} 次已启动或预留的评测调用 · 渠道实测</p>
<div class="note"><b>v2 草案真实试测 · 评委未校准</b><br>模型标识由网关声明，未独立核验。任务尚待独立人审；重大边界争议保留未决。按合格率下界展示顺序，不宣称模型能力排名已经成立。</div>
<div class="scroll"><table><thead><tr><th>模型 / 渠道</th><th>合格率下界–上界</th><th>通过 / 未通过 / 未决</th><th>任务族 95% 区间</th><th>任务族 / 计划试验</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<p>下界把未决计为失败，上界把未决计为通过。缺失、传输失败、评委分歧都保留在分母。点击模型查看完整转录和原始评委响应。</p>
<h2>分领域表现</h2><div class="scroll"><table><thead><tr><th>任务领域</th>{headings}</tr></thead><tbody>{breakdown}</tbody></table></div>
<footer>本地实测导出 · 任务族等权 · 单次采样 · 不代表生产成功率 · 人工复核待完成<br>金额未估计：本批仅记录调用与端点返回的 token 用量。原始 JSON 与每份详情页同目录保存。</footer></main></html>"""
    output.write_text(page, encoding="utf-8")
    index: Json = {
        "schema_version": "2.0",
        "models": [
            {
                "model": r["manifest"]["config"]["model"],
                "summary": r["summary"],
                "run_id": r["manifest"]["run_id"],
            }
            for r in reports
        ],
    }
    write_json(output.with_suffix(".json"), index)
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path, nargs="+")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    build(args.runs, args.out)
