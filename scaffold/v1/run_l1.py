#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""参考脚手架 v1 —— L1 runner。

把一道 L1 场景（scenarios/L1/*.yaml）喂给指定供应商，多轮对话按
follow_up_turns 推进，配对题（type: paired）分别跑中性版与施压版，
转录存为 JSON 供评委使用。

用法：
  /usr/bin/python3 run_l1.py --scenario ../../scenarios/L1/L1-PRD-001.yaml \
      --provider mock [--providers providers.yaml] [--out ../../transcripts] \
      [--samples 1]

注意：本机 PATH 里的 python3 是 ServBay alias，会挂起；请显式用 /usr/bin/python3。
"""
import argparse
import datetime
import json
import os
import sys
import urllib.request

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_scaffold():
    cfg = load_yaml(os.path.join(HERE, "config.yaml"))
    sp_path = os.path.join(HERE, cfg["l1"]["system_prompt"])
    with open(sp_path, "r", encoding="utf-8") as f:
        system_prompt = f.read().strip()
    return cfg, system_prompt


def http_json(url, headers, payload, timeout=120):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "User-Agent": "collab-eval-scaffold/v1", **headers},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def call_model(provider, system_prompt, messages, l1cfg):
    """messages: [{role: user|assistant, content: str}, ...]，返回助手文本。"""
    api = provider.get("api", "openai")
    if api == "mock":
        last = messages[-1]["content"]
        return "[mock:%s] 收到第 %d 轮消息（前 40 字：%s）" % (
            provider.get("model", "echo"), len(messages), last[:40].replace("\n", " "))
    if api == "openai":
        payload = {
            "model": provider["model"],
            "messages": [{"role": "system", "content": system_prompt}] + messages,
            "temperature": l1cfg["temperature"],
            "max_tokens": l1cfg["max_tokens"],
        }
        headers = {"Authorization": "Bearer " + os.environ[provider["api_key_env"]]}
        data = http_json(provider["base_url"].rstrip("/") + "/chat/completions", headers, payload)
        return data["choices"][0]["message"]["content"]
    if api == "anthropic":
        payload = {
            "model": provider["model"],
            "system": system_prompt,
            "messages": messages,
            "temperature": l1cfg["temperature"],
            "max_tokens": l1cfg["max_tokens"],
        }
        headers = {
            "x-api-key": os.environ[provider["api_key_env"]],
            "anthropic-version": "2023-06-01",
        }
        data = http_json(provider["base_url"].rstrip("/") + "/v1/messages", headers, payload)
        return "".join(b.get("text", "") for b in data["content"])
    raise ValueError("未知 api 类型: %s" % api)


def run_conversation(provider, system_prompt, first_prompt, follow_ups, l1cfg):
    """跑一段完整对话，返回 turns 列表。"""
    messages = []
    turns = []
    user_inputs = [first_prompt] + [t["user"] for t in (follow_ups or [])]
    for user_text in user_inputs:
        messages.append({"role": "user", "content": user_text})
        reply = call_model(provider, system_prompt, messages, l1cfg)
        messages.append({"role": "assistant", "content": reply})
        turns.append({"user": user_text, "assistant": reply})
    return turns


def run_scenario(scenario, provider, system_prompt, l1cfg, sample_idx):
    result = {
        "scenario_id": scenario["id"],
        "sample": sample_idx,
        "conversations": {},
    }
    if scenario.get("type") == "paired":
        for key in ("prompt_neutral", "prompt_pressured"):
            result["conversations"][key] = run_conversation(
                provider, system_prompt, scenario[key].strip(),
                scenario.get("follow_up_turns"), l1cfg)
    else:
        result["conversations"]["main"] = run_conversation(
            provider, system_prompt, scenario["prompt"].strip(),
            scenario.get("follow_up_turns"), l1cfg)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True, help="L1 场景 YAML 路径")
    ap.add_argument("--provider", required=True, help="providers 文件中的 name")
    ap.add_argument("--providers", default=os.path.join(HERE, "providers.yaml"))
    ap.add_argument("--out", default=os.path.join(HERE, "..", "..", "transcripts"))
    ap.add_argument("--samples", type=int, default=None, help="覆盖 samples_per_item")
    args = ap.parse_args()

    cfg, system_prompt = load_scaffold()
    l1cfg = cfg["l1"]
    scenario = load_yaml(args.scenario)
    providers = {p["name"]: p for p in load_yaml(args.providers)["providers"]}
    if args.provider not in providers:
        sys.exit("providers 文件里没有 %r，可选：%s" % (args.provider, sorted(providers)))
    provider = providers[args.provider]
    n = args.samples or l1cfg.get("samples_per_item", 1)

    ts = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    out_dir = os.path.join(args.out, scenario["id"], args.provider)
    os.makedirs(out_dir, exist_ok=True)

    for i in range(1, n + 1):
        record = {
            "scaffold_version": cfg["version"],
            "provider": {"name": args.provider, "model": provider.get("model"),
                         "api": provider.get("api")},
            "temperature": l1cfg["temperature"],
            "timestamp": ts,
            **run_scenario(scenario, provider, system_prompt, l1cfg, i),
        }
        out_path = os.path.join(out_dir, "%s-sample%d.json" % (ts, i))
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        print("已写入 %s（%d 段对话）" % (out_path,
              len(record["conversations"])))


if __name__ == "__main__":
    main()
