# 0025 · 定时任务与后台模型调用上限

- **状态**：已采纳（2026-10-02，任务 30；Q12 按推荐确认）
- **日期**：2026-10-02
- **影响**：新增依赖 `apscheduler` 3.x；新增 `backend/app/scheduler/`、`scheduler_runs` 表；租户设置加“后台每日 token 上限”，学习者设置加各后台功能的开关；`features.yaml` 里后台功能登记为 `timing: background`。

## 背景
P2 开始出现不由学习者当下操作触发的模型调用：抓取 RSS 后为订阅者预改写文章、每周诊断、做完一组练习后预生成下一组、为第二天的词预生成 AI 例句、每日计划预计算。PLAN 一直定的是 APScheduler（不上 Celery）。约束：

- 线上是低配服务器，compose 里后端只跑一个容器、一个 uvicorn 进程（`backend/Dockerfile` 的 CMD 没有 `--workers`）。现有的后台工作（附件处理、`memory/worker.py` 的 `ReflectionWorker`）也都是进程内 asyncio，没有任务队列。
- 后台调用花的是租户自己配置的模型和 token（ADR 0004），学习者看不到“点了什么”，更需要上限和开关；ADR 0014 要求每个会调用模型的功能都公示。

核实（2026-10-02）：APScheduler 最新稳定版 3.11.3（2026-06-28，MIT，纯 Python）；4.0 仍是 alpha（4.0.0a6），不用。

## 决定
1. **调度器**：进程内 `AsyncIOScheduler`（APScheduler 3.x），在 FastAPI lifespan 里启动和关闭；任务定义在 `backend/app/scheduler/` 的代码里，启动时注册，不用 APScheduler 的持久化 job store。
2. **单实例约定**：部署只跑一个后端进程（compose 已是如此），README 和 `docker-compose.yml` 注释里写明。以后要多实例时，用 Postgres advisory lock 保证同一任务只有一个实例在跑，不在 P2 做。
3. **幂等与补跑**：`scheduler_runs`（任务名、上次开始、上次成功、上次错误）记录每个任务的运行情况；每个任务按“上次成功以来的新数据”工作，重复执行不会产生重复结果（比如文章按 URL 去重、改写按（租户、文章、等级）缓存）。启动时如果某个任务已经错过了一个周期，就补跑一次，不逐个补齐所有错过的周期。
4. **任务清单**（P2 内逐步加入）：抓取 RSS（每 2 小时）、为订阅者预改写新文章、每周诊断（P2d）、每日计划预计算（P2e）、预生成 AI 例句（任务 44，先看覆盖率再定范围）。做完一组练习后预生成下一组是事件触发，不是定时任务，但同样受下面的上限和开关约束。
5. **每日上限（Q12）**：租户级“后台每日 token 上限”，默认保守（100,000 tokens，设置页可改，0 表示关闭全部后台调用）。用量从 `llm_usage` 按租户、当天（UTC）、后台任务的 task 汇总；超过上限后当天的后台任务跳过，并在 `scheduler_runs` 和设置页里显示“今天的后台额度已用完”。上限只管后台调用，不管学习者当下触发的调用（对话、批改、点按钮生成），也不管回复后的记忆反思（对话的一部分）。
6. **学习者开关**：每个后台功能学习者都可以在设置里关掉。默认开启诊断和文章预改写，默认关闭 AI 例句预生成。练习的“预生成下一组”默认开启。
7. **公示**：每个后台功能在 `features.yaml` 登记为 `timing: background`、写明触发时机和默认估计（ADR 0014），在 `docs/agent-tools.md` 列出（ADR 0013）；后台任务产生的结果（诊断、改写过的文章）在界面上标明是私教在后台做的。

## 取舍
- 进程内调度只能单实例；对低配单机部署这是最简单、内存最小的方案。多实例时加 advisory lock 即可，不用换架构。
- 不用 APScheduler 的持久化 job store：任务都在代码里定义，持久化反而会让改了代码后的旧任务残留；补跑靠 `scheduler_runs` 自己判断，更透明。
- 也可以照 `ReflectionWorker` 自己写 asyncio 循环，少一个依赖；但 cron 表达式、错过执行的处理、合并重叠执行这些都要自己写，APScheduler 3.x 是成熟的纯 Python 库，内存占用很小。
- 默认上限是猜的保守值，P2 Demo 实测后按实际用量再调。按 UTC 切天对不在 UTC 时区的学习者会有偏差，上限只是成本保护，不追求精确。

## 落地记录（任务 40，2026-10-07）
Q40a–f 按推荐确认。
- **调度**（40.1）：`backend/app/scheduler/jobs.py` 定义 `Job`（名字 + APScheduler trigger + `async run(ctx) -> 跳过原因 | None`）和 `JOBS`（任务 40 时为空，第一个是任务 41 的 RSS 抓取）；`service.py` 的 `Scheduler`：APScheduler 只负责触发（`coalesce`），运行在自己的 asyncio 任务里，同一任务正在跑时新的触发丢掉；`scheduler_runs` 记开始、结束、上次成功、状态（running / ok / skipped / error）、跳过原因、错误。启动时把上次停机打断的标 error，再对“上次结束后又到了一个周期”或从没跑过的任务补跑一次。`SCHEDULER_ENABLED`（默认 true；E2E 后端关掉，pytest 不跑 lifespan，测试直接调任务）。
- **记账与上限**（40.2，Q40a、Q40b）：`llm_usage.background`，调用时 metadata 带 `background: True`（预生成和现生成共用 task 名，所以不靠 task 名区分）；`tenants.background_daily_tokens`（默认 100,000，≥ 0）；`scheduler/budget.py` 汇总当天（UTC）后台输入 + 输出 token，每项后台工作开始前判，允许最后一项略超。
- **开关**（40.3，Q40c）：`user_background_prefs`（没有行用默认值），功能登记在 `scheduler/prefs.py`，目前只有 `practice_prefetch`（默认开）。接口 `GET/PUT /me/background`（学习者只看到额度状态 ok / exhausted / off）、`GET/PUT /tenant/background`（owner / admin：上限、今天已用、各任务运行情况）。**和计划不同**：`PracticeWorker.prefetch_enabled` 保留为进程级总开关（测试用），学习者开关另外判。
- **设置页**（40.4、Q40e）：“后台任务”一节，学习者开关挂对应功能的 AI 标记；额度用完 / 关闭只显示一句提示，不打断。
- 迁移：`71d583d62096`（`scheduler_runs`）、`d4236aefe2d0`（`llm_usage.background`、`tenants.background_daily_tokens`）、`94afd2b1f522`（`user_background_prefs`）。

