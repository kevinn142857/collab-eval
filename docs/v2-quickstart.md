# 做好 v2：本地运行与复核

v2 已实现离线可验证的软件闭环。现有 20 族 / 80 条件和 100 条校准样例都是待独立人审的草案；没有真实模型新成绩。v1 CLI 和历史数据原样保留。

## 安装与离线演示

Python 3.9+；沿用 `requirements.txt`。本机使用 `/usr/bin/python3`；其他环境可使用自己的 `python`。

```bash
python -m pip install -r requirements.txt
python -m collab_eval.cli v2 validate
python -m collab_eval.cli v2 demo --out .runs/demo
```

打开 `.runs/demo/index.html`。此页用构造答案和模拟判定展示通过、失败和缺评委情况，不应被引用为模型能力分。输出目录须为空；重建请选新目录。文件包含完整证据，默认私有。

## 冻结计划、运行和恢复

```bash
python -m collab_eval.cli v2 plan --out .runs/mock --samples 2 --max-calls 280
python -m collab_eval.cli v2 run .runs/mock
python -m collab_eval.cli v2 report .runs/mock --out .runs/mock/report.html
```

没有 `--provider` 时仅运行 mock；mock 答案不自动获得有效判定。全部未判定时报告为 0–100% 未决边界，不会显示零能力或满分。

计划嵌入完整题目与配置快照，记录身份哈希。每族各条件独立运行完整对话；多轮中的授权条件是顺序干预，当前不能推断隔离的授权因果效应。报告中的压力有害变化仅是探索性失败变化代理。独立人审、同前缀分叉与中性后续对照是正式实验前的门槛。

`max_calls` 是整批候选 API 调用次数上限，单次输出受 `max_tokens` 限制；**不是金额保证**。本版本没有价格表和美元预算控制，付费批跑前须根据端点单价与输入长度另行预算。评委调用另设上限。部分输出、传输错误和已启动但中断的试验保留，不通过恢复挑选好答案；重新采样请建新批次。

对同一目录再次执行 `run` 只运行未启动的试验，不替换已有记录。所有写入使用 `.write.lock`。崩溃后若有遗留锁，先确认没有活动进程，再由操作者删除锁；不会自动猜测过期而并发覆盖。

## 外部候选模型与评委

将 `config/provider.v2.example.yaml` 复制到本地文件，填写端点、模型、参数和环境变量名，密钥仅设在环境变量中。首发适配 OpenAI-compatible Chat Completions；不声称覆盖 Responses、厂商原生 API 或所有模型参数。

```bash
python -m collab_eval.cli v2 plan --provider config/local-provider.yaml --out .runs/live --samples 2 --max-calls 280
# 阅读冻结计划和费用估算后，以下命令才会向配置端点发送题目。
python -m collab_eval.cli v2 run .runs/live --execute --allow-draft
```

`--allow-draft` 允许试点，不改变草案状态。脚本只执行单次传输尝试，无隐藏重试；超时 120 秒；不会跨 HTTP 重定向发送认证头。

评委配置格式与候选相同，但系统提示固定为 v2 证据核对协议。`judge` 会将该批完整转录发送到所选评委端点；私有材料须先确认允许发往该端点。

```bash
python -m collab_eval.cli v2 judge .runs/live --provider config/local-judge-a.yaml --max-calls 160 --execute
python -m collab_eval.cli v2 judge .runs/live --provider config/local-judge-b.yaml --max-calls 160 --execute
```

使用两个不同模型的评委；同一模型/端点换名字不会被当作两个独立评委。同名评委绑定原配置，参数变化须新名称。`max_calls` 对该评委在此批的所有已启动调用累计计数，恢复时仍累计；无效 JSON、缺引用和中断不会被静默重试。

所有自动评委当前均标“未校准”。100 条草案样例不是已完成的独立验收集；软件不会开放虚假的“已校准”开关。正式发布的校准导入和签核流程需待独立审阅完成后接入。

## 人工裁决

从报告选取试验和标准，创建 JSON 文件，例如：

```json
{
  "trial_id": "COPY_FROM_REPORT",
  "criterion_id": "scope",
  "status": "fail",
  "reviewer": "reviewer-id",
  "reason": "第二轮修改了仍明确禁止修改的条款。",
  "citations": [{"turn": 2, "quote": "COPY_EXACT_ASSISTANT_QUOTE"}]
}
```

```bash
python -m collab_eval.cli v2 adjudicate .runs/live --file decision.json
python -m collab_eval.cli v2 report .runs/live --out .runs/live/report.html
```

必须是回答里真实存在的引用。工具校验来源和结构，不能替代人类语义审阅或验证填写者身份。对同一试验标准的裁决不允许覆盖；纠正需新复核批次。原始评委判定继续展示。

重大边界失败必须经人工确认；未确认是未决。无需认错的标准预先标不适用，不能通过评委临时填不适用跳过适用标准。用户认为题目本身有误时应保留未决并修改任务版本，不借单条裁决重写适用性。

## 配对比较

```bash
python -m collab_eval.cli v2 compare --a .runs/version-a --b .runs/version-b --margin 0.05 --out .runs/comparison.html
```

差值是 B − A。任务快照、重复次数、轨道、计分版本、评委配置和逐试验分配必须一致，否则标为不可比较。草案、模拟或未校准结果只能提供探索性差值，不能宣布实质改善或等效。

所有预定试验保留在分母；未决上下界与任务族 bootstrap 区间分别展示。每领域不足两个独立任务族不估计族间区间。重复采样不能增加独立族数；便利抽样的诊断集不代表生产发生率。

## 验证与当前范围

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
ruff check collab_eval/v2 tests/test_v2*.py
ruff format --check collab_eval/v2 tests/test_v2*.py
mypy --strict collab_eval/v2
python -m collab_eval.cli v2 demo --out .runs/build-check
```

Ruff 和 mypy 仅覆盖新增 v2 与相应测试（mypy 覆盖 v2 源码），不将未迁移的 v1 宣称为严格类型代码。CI 同时回放 v1 以验证兼容性。

本批实现的是阶段 A 的软件与草案材料，尚不满足独立人审验收。60 族稳定集、真实模型跑批、价格预算、交互澄清分支、正式校准导入、沙箱执行、公开结果目录和持续监测仍须按设计后续阶段交付。本次没有自动发布网站或创建定时任务。

## 真实试测榜单导出

对已产生真实记录的运行目录，可导出直接展示各模型合格率范围的本地榜单：

```bash
python -m collab_eval.v2.leaderboard .runs/run-a .runs/run-b --out .runs/live-board/index.html
```

输入必须是相同任务快照的 live 运行，模拟数据被拒绝。详情页及 JSON 随榜单一起导出；未完成、评委分歧及待人工裁决均保留未决。显示顺序不是统计确认的名次。当前网关返回的模型名称仍只是渠道声明。

Python `run(..., workers=8)` 与 `judge_run(..., workers=8)` 支持最多 8 个并发独立试验；默认仍为 1。整个目录持有独占写锁，候选调用在共享锁内预留预算并落盘后发起请求。评委任务先预留并持久化再调度；因此崩溃时预留未发送的任务也会保留中断记录，不自动重试。多轮试验内部依然按顺序执行。
