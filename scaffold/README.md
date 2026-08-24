# 参考脚手架（Reference Scaffold）

「固定壳，换模型」的壳。所有模型在同一套脚手架下跑，分数差异才能归因于模型。
版本随榜单发布；**定稿即冻结**，要改就升版本号并全量重跑。

## 铁律

1. 系统提示只写三件事：角色、可用工具、输出格式。
2. **禁止行为指导**（「要敢于反驳」「先核对前提」之类）——那是五维度要测的对象，写进提示等于把答案印在考卷上。
3. 不针对任何单一模型调优。它是考场，不是选手。
4. 每次改动须过第十人审查，专门核对第 2 条。

## v1 内容

| 文件 | 说明 |
|---|---|
| `v1/system_prompt.txt` | 冻结的系统提示（三段：角色 / 工具 / 输出） |
| `v1/config.yaml` | L1 运行参数（温度 0、max_tokens 2048）；L2 配置预留未实现 |
| `v1/run_l1.py` | L1 runner：单题/配对题、多轮追问、转录存 JSON |
| `v1/providers.example.yaml` | 供应商配置模板（openai / anthropic / mock 三种 api） |

## 用法

```bash
cd scaffold/v1
cp providers.example.yaml providers.yaml   # 填入自己的渠道与 key 环境变量
/usr/bin/python3 run_l1.py --scenario ../../scenarios/L1/L1-PRD-001.yaml --provider mock
```

转录写入 `transcripts/<题目id>/<渠道>/<时间戳>-sampleN.json`，含脚手架版本、
渠道、温度与逐轮对话，供评委（人工或 LLM）按核对清单打分。

注意：本机 PATH 里的 `python3` 是 ServBay alias 且会挂起，务必用 `/usr/bin/python3`。

## 验收（落地计划阶段 0）

3 个真实模型都能在其上跑通 L1-PRD-001。mock 渠道已验证链路；真实模型待填 key 后执行：

```bash
for p in claude gpt <第三家>; do
  /usr/bin/python3 run_l1.py --scenario ../../scenarios/L1/L1-PRD-001.yaml --provider $p
done
```
