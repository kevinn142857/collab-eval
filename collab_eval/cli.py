#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一入口：collab-eval <子命令> [参数]

  validate        校验题库（配比/证据标注/红线与配对占比）
  bank-page       渲染审题页 HTML          bank-page <out.html>
  run             用参考脚手架跑一题       run --scenario <yaml> --provider <name>
  judge           清单评委                 judge --all | --transcript <json> --judge <name>
  aggregate       聚合：五维/CI/Kappa/黄金集
  controls        防刷分套路对照           controls --judge <name>
  blind           模型盲验                 blind --provider <name>
  blind-compare   盲验与埋点对照           blind-compare --checker <name>
  report          结果页                   report <out.html>
  selfeval        自评出卷/收卷            selfeval sheet | assemble --answers <json>

本机 PATH 里的 python3 是 ServBay alias 且会挂起，请用：/usr/bin/python3 -m collab_eval.cli <子命令>
"""
import os, runpy, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
COMMANDS = {
    "validate": ("collab_eval.bank", None),
    "bank-page": ("collab_eval.bank_page", None),
    "run": (None, os.path.join(ROOT, "scaffold", "v1", "run_l1.py")),
    "judge": ("collab_eval.judge", None),
    "aggregate": ("collab_eval.aggregate", None),
    "controls": ("collab_eval.controls", None),
    "blind": ("collab_eval.blind", None),
    "blind-compare": ("collab_eval.blind_compare", None),
    "report": ("collab_eval.report", None),
    "selfeval": ("collab_eval.selfeval", None),
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help") or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(0 if len(sys.argv) >= 2 and sys.argv[1] in ("-h", "--help") else 1)
    cmd = sys.argv[1]
    sys.argv = [sys.argv[0] + " " + cmd] + sys.argv[2:]
    module, path = COMMANDS[cmd]
    if path:
        runpy.run_path(path, run_name="__main__")
    else:
        runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
