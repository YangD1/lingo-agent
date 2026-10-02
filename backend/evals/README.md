# 评估集（`backend/evals/`）

P2 的最小评估集（计划 Q13、任务 36）：检查把关学习者所见内容的模型调用——critic 能不能拒掉已知坏题、批改能不能判对已知答案。数据都是合成的，不含真实用户数据。

## 组成

- `datasets/<name>.yaml`：用例和门槛。`thresholds` 把指标名映射到要达到的准确率（0–1），每条用例有唯一 `id`，其余字段由评估器自己读。
- `cassettes/<name>.json`：真实模型的录制结果。键是“任务 + 消息 + 输出结构”的哈希，所以提示词、代码拼出的消息或结构一改，回放就对不上，直接失败并提示重录，不会拿旧答案去评新提示词（Q36a）。
- 评估器：在 `registry.py` 的 `EVALUATORS` 登记，走和应用相同的代码路径（拼消息 → 结构化调用 → 代码判定），每条用例返回若干指标的对错。

## 运行

```bash
make eval                                                  # 回放，不需要 key 和数据库；pytest / CI 也会跑（evals/test_replay.py）
make eval-live ARGS='--email you@example.com'              # 用开发库里这个账号所在租户的连接，走 provider 层（Q36b）
make eval-live ARGS='--email you@example.com --record'     # 同上，并重写录制文件
make eval ARGS='critic'                                    # 只跑某几个
```

退出码：0 门槛全达到，1 有门槛没达到或调用失败，2 录制过期需要重录。重录时只要有一条调用失败就不写文件；写的时候整份替换，不再用到的录制会被删掉。真实模型模式不记 `llm_usage`。
