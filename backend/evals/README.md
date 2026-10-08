# 评估集（`backend/evals/`）

P2 的最小评估集（计划 Q13、任务 36）：检查把关学习者所见内容的模型调用——critic 能不能拒掉已知坏题，批改能不能判对已知答案。数据都是合成的，不含真实用户数据。

## 组成

| 名字 | 数据集 | 走的代码 | 门槛 |
|---|---|---|---|
| `critic` | `datasets/critic.yaml`：坏题 26 条（答案键错、不止一个对、不考目标语法点、英文不自然或指令不清、事实错误、难度标错）、好题 18 条，六种题型都有 | `critic_messages` → `exercise_critic` → `drafts.judge`，一题一次调用 | `bad_rejected` ≥ 90%、`good_passed` ≥ 90% |
| `grader` | `datasets/grader.yaml`：31 条代码判不了、会交给模型的答案（开放题不在参考答案里、find_fix 选对位置但改法不在列表里），应判对 / 应判错都有，部分带应找出的其他错误 | `grade_messages` → `exercise_grade` → `grader.verdict` | `verdict_right` ≥ 90% |
| `diagnosis` | `datasets/diagnosis.yaml`：12 条（任务 46.6）。8 条有真规律：前置语法点是根因（过去分词 → 现在完成时、过去完成时 → 第三条件句、三单 → 主谓一致）、易混语法点互相顶替（will / going to、be / do、used to / 一般现在时），一条两个目标各有根因，一条错句里夹着让模型引用不存在证据的“指令”；3 条没有规律（零散错误、只是把语法点说明重复一遍不算根因）；一条英文讲解 | `diagnose_messages` → `diagnose` → `checks.check`，邻域按 `graph.neighborhood` 的规则从语法目录拼出，不需要数据库 | `root_found` ≥ 80%、`no_cause_without_pattern` ≥ 60%、`citations_hold` ≥ 90% |

不设门槛、只报告的指标：critic 的 `rejects:<缺陷>`（看哪类坏题漏过），批改的 `other_mistakes_found`、`no_extra_mistakes`（对的答案没被挑出多余错误）。

- **数据集**：`thresholds` 把指标名映射到要达到的准确率，写在数据里而不是代码里（Q36c）；每条用例有唯一 `id`，其余字段由评估器读，加载时校验（题目要能通过 `formats.py`，批改用例必须真的会走到模型）。
- **录制**：`cassettes/<名字>.json`。键是“任务 + 消息 + 输出结构”的哈希，所以提示词、代码拼出的消息或结构一改，回放就对不上，直接失败并提示重录（Q36a），不会拿旧答案评新提示词。critic 用例里的生成器难度评分不进提示词，改它不用重录。
- **评估器**：在 `registry.py` 的 `EVALUATORS` 登记，实现 `runner.Evaluator`（`name` + `run_case`）。

## 运行

```bash
make eval                                               # 回放，不需要 key 和数据库；pytest / CI 也会跑（evals/test_replay.py）
make eval ARGS='critic'                                 # 只跑某几个
make eval-live ARGS='--email you@example.com'           # 用开发库里这个账号所在租户的连接，走 provider 层（Q36b）
make eval-live ARGS='--email you@example.com --record'  # 同上，并重写录制文件
```

退出码：0 门槛全达到；1 有门槛没达到或调用失败；2 录制过期，需要重录。重录时只要有一条调用失败就不写文件；写的时候整份替换，不再用到的录制会被删掉。没有录制文件的数据集回放时跳过。真实模型模式不记 `llm_usage`。

## 什么时候要重录

改了 `prompts/exercise_critic.md`、`prompts/exercise_grade.md`、语法目录、`rules.yaml` 的难度量表，或者改了 `messages.py` / `grader.py` 拼消息的方式，回放就会失败。用一个配好模型的账号跑 `make eval-live ARGS='--email … --record'`，先看报告：失败的用例逐条看原因，分清是用例本身有歧义（改用例）还是模型或提示词的问题（改提示词，或者作为已知弱点留着）。

## 诊断评估集（任务 46.6）

还没有录制：回放时跳过。`citations_hold` 看模型原始输出（代码校验之前）是否只引用了给它看过、且校验认可的语法点和错句；代码校验会把不合格的引用丢掉，所以它衡量的是模型本身，不影响学习者看到的结果。门槛是第一次设的，录制后按报告调整。

## 当前录制（2026-10-02，gpt-5.5，经 OpenAI 兼容中转）

- critic：坏题拒 24/26，好题过 18/18。漏过的两条是已知弱点：`translate-yangtze-longest`（事实错误，三次运行都没拒）、`choice4-a-or-the`（a / the 都对，三次只拒一次）。
- 批改：判对 31/31，其他错误 4/4 找到，对的答案没有被挑出多余错误。
- 这次实测修了 critic 提示词：说明 `rewrite_own` 的原句是学习者自己写的。之前 critic 会因为“your sentence”没有上下文而拒掉好题。
