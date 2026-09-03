#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外部提交：打包（manifest + 逐份转录哈希）与校验（CI 在 PR 上跑）。

  collab-eval submission make --model <provider名> [--out submissions/]
  collab-eval submission verify <submissions/xxx/>    # 退出码非 0 = 拒收

manifest 记录：题库哈希（防止改题）、脚手架系统提示哈希（防止换壳）、每份转录 sha256（防篡改）。
提交只含转录，不含分数——评分由平台评委统一跑（信任三级见 IMPLEMENTATION_PLAN）。
"""
import argparse, datetime, glob, hashlib, json, os, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def bank_hash():
    h = hashlib.sha256()
    for f in sorted(glob.glob(os.path.join(ROOT, "scenarios", "L1", "*.yaml"))):
        h.update(os.path.basename(f).encode()); h.update(open(f, "rb").read())
    return h.hexdigest()


def scaffold_hash():
    return sha(os.path.join(ROOT, "scaffold", "v1", "system_prompt.txt"))


def make(model, out_root):
    files = sorted(glob.glob(os.path.join(ROOT, "transcripts", "*", model, "*.json")))
    if not files:
        sys.exit("没有 %s 的转录" % model)
    latest = {}
    for f in files:  # 每题取最新
        sid = f.split(os.sep)[-3]
        if sid not in latest or f > latest[sid]:
            latest[sid] = f
    out = os.path.join(out_root, model)
    os.makedirs(os.path.join(out, "transcripts"), exist_ok=True)
    entries = []
    for sid, f in sorted(latest.items()):
        rec = json.load(open(f, encoding="utf-8"))
        dst = os.path.join(out, "transcripts", "%s.json" % sid)
        json.dump(rec, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        entries.append({"scenario_id": sid, "file": "transcripts/%s.json" % sid, "sha256": sha(dst),
                        "scaffold_version": rec.get("scaffold_version"), "temperature": rec.get("temperature")})
    manifest = {"model": model, "model_id": rec["provider"].get("model"), "api": rec["provider"].get("api"),
                "created": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "bank_sha256": bank_hash(), "scaffold_prompt_sha256": scaffold_hash(),
                "n_items": len(entries), "trust_tier": "community", "items": entries}
    json.dump(manifest, open(os.path.join(out, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("打包 %d 份转录 → %s" % (len(entries), out))


def verify(path):
    errors = []
    mp = os.path.join(path, "manifest.json")
    if not os.path.exists(mp):
        return ["缺 manifest.json"]
    m = json.load(open(mp, encoding="utf-8"))
    for k in ("model", "bank_sha256", "scaffold_prompt_sha256", "items"):
        if k not in m:
            errors.append("manifest 缺字段 %s" % k)
    if m.get("bank_sha256") != bank_hash():
        errors.append("题库哈希不一致：提交用的题库与当前题库不同（改题或版本不符）")
    if m.get("scaffold_prompt_sha256") != scaffold_hash():
        errors.append("脚手架系统提示哈希不一致：疑似换壳")
    known = {os.path.basename(f)[:-5] for f in glob.glob(os.path.join(ROOT, "scenarios", "L1", "*.yaml"))}
    for it in m.get("items", []):
        f = os.path.join(path, it.get("file", ""))
        if not os.path.exists(f):
            errors.append("缺转录 %s" % it.get("file")); continue
        if sha(f) != it.get("sha256"):
            errors.append("转录被改动：%s" % it["file"])
        if it.get("scenario_id") not in known:
            errors.append("未知题目 %s" % it.get("scenario_id"))
        rec = json.load(open(f, encoding="utf-8"))
        if not rec.get("conversations") or any(not turns for turns in rec["conversations"].values()):
            errors.append("转录为空：%s" % it["file"])
        if rec.get("temperature") not in (0, 0.0, None):
            errors.append("温度非 0：%s" % it["file"])
    return errors


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("make"); a.add_argument("--model", required=True); a.add_argument("--out", default=os.path.join(ROOT, "submissions"))
    b = sub.add_parser("verify"); b.add_argument("path")
    args = ap.parse_args()
    if args.cmd == "make":
        make(args.model, args.out)
    else:
        errs = verify(args.path)
        if errs:
            print("拒收（%d 项）:" % len(errs)); [print("  -", e) for e in errs]; sys.exit(1)
        print("校验通过")


if __name__ == "__main__":
    main()
