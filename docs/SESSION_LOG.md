# 会话交接日志

> 新记录追加在**最上方**。每条包括：做了什么 / 未完成（精确到文件或函数）/ 下一步 / 踩坑。

---

## 2026-10-02 · 任务 37 完成（Supervisor 主图）

- **做了什么**：Q37a–c 按推荐确认（自由对话分类和路由活动步骤挪到 38；确定信号的路由不记步骤；coach 用子图）。37.1 `agents/routing.py` + `_reply` 按路由组装来源；37.2 主图 `load_context → supervisor → {tutor, grammar_coach}`，`supervisor` 返回 `Command(goto=route)`，开场提示按 coach 定，`_run_graph` 用 `subgraphs=True`；37.3 ADR 0023 / P2 计划落地记录、`docs/agent-tools.md`。pytest 1165、E2E 46 全过。
- **未完成**：无。本地领先 origin 约 10 个提交未推送；Docker 未重建（36.4 改了 critic 提示词，37 改了对话图，重建后才生效）。
- **下一步**：任务 38 先拆子任务、和用户确认。38 现在还包括（Q37a/b）：自由对话的轻量分类（task `route`，Pydantic 枚举，失败留在 tutor，`features.yaml` 登记）和“转给了写作 coach”的活动步骤。新 coach 的接法：`routing.Route` 加值、`chat_graph.py` 加一个子图（`compile(checkpointer=False)`）和 `COACH_NODES`、`supervisor` 的 `Command` 类型、`_reply` 的 `match route` 加分支。要测：tutor 留下工具调用后下一轮转给不带工具的 coach（有的厂商要求带工具定义才接受历史里的工具消息）。
- **踩坑**：LangGraph 子图默认会自己存 checkpoint，把输入（含 `UntrackedValue` 的学习者记忆、练习指引）写进 `checkpoint_writes`——原有隐私测试抓到，子图改 `checkpointer=False`。子图里的 token 和自定义事件要 `astream(..., subgraphs=True)` 才收得到，返回值变成 `(namespace, mode, part)`。

---

## 2026-10-02 · 任务 36.4 完成，任务 36 完成（评估集录制）

- **做了什么**：用用户临时给的 gpt-5.5（OpenAI 兼容中转）在开发库临时账号上跑了三次真实模型，录制 `evals/cassettes/critic.json`（44 次）和 `grader.json`（31 次）入库，文件里没有密钥；临时账号、租户和连接已用 SQL 删除（没有删账号接口）。结果：坏题拒 24/26、好题过 18/18、批改判对 31/31。实测带来的改动：`prompts/exercise_critic.md` 说明 `rewrite_own` 的原句是学习者自己写的；两条有歧义的用例换掉；好题的生成器难度评分按真实 critic 校准；critic 失败详情显示评分差异。文档：`evals/README.md`、P2 计划落地记录、ADR 0005。pytest 1157 全过。
- **未完成**：无。已知 critic 弱点留在集里：事实错误（`translate-yangtze-longest`）、a / the 两个都对（`choice4-a-or-the`）。
- **下一步**：任务 37（Supervisor 路由），开工前先拆子任务、和用户确认。本地领先 origin 若干提交，未推送。
- **踩坑**：生成器难度评分不进 critic 的提示词，所以改它不影响录制键，可以录完再校准。手写评分时 A1 题的词汇不能标 below_target。同一用例三次运行结果会变（a / the 那条），单次录制只是一份样本。

---

## 2026-10-02 · 任务 36.3 完成（批改评估集）

- **做了什么**：`evals/datasets/grader.yaml` 31 条（只收代码判不了、真的会走到模型的答案：开放题不在参考答案里的、find_fix 选对位置但改法不在列表里的）+ `evals/grader.py`（走 `grade_messages` → `exercise_grade` → `grader.verdict`；`verdict_right` 门槛 90%，`other_mistakes_found` / `no_extra_mistakes` 只报告不设门槛）；登记到 `EVALUATORS`。单测 6 个；pytest 1155 全过。
- **未完成**：36.4——两个数据集都还没录制，`make eval` 现在两个都跳过。
- **下一步**：36.4 需要用户临时给 key：按 `real-model-test-key` 记忆的做法建临时账号、在设置里加连接（`exercise_critic`、`exercise_grade` 走默认路由即可），`make eval-live ARGS='--email <临时账号>'` 先跑一遍看结果；失败的用例逐条看 detail，判断是用例本身有歧义（改用例）还是模型问题（记下来）；满意后加 `--record` 录制、入库，删临时账号。然后补全 `evals/README.md`、P2 计划落地记录、ADR 0005“评估”一节补一句。
- **踩坑**：YAML 流式映射里答案带 `?` 会解析失败，答案统一加引号。

---

## 2026-10-02 · 任务 36.2 完成（critic 评估集）

- **做了什么**：`evals/datasets/critic.yaml`（坏题 26 条，六类缺陷；好题 18 条，六种题型各 3）+ `evals/critic.py`（一题一次调用，走 `critic_messages` → `exercise_critic` → `drafts.judge`，生成器难度从用例的 `ratings` 用 `prior_difficulty` 算）；登记到 `EVALUATORS`；没有录制文件时 `make eval` 和 `evals/test_replay.py` 跳过并提示录制。单测 5 个；pytest 1149 全过。
- **未完成**：critic 还没录制（36.4）。好题的难度评分是手写的，真实 critic 评分若普遍偏离超过 `critic_max_gap`（0.7），好题会因“难度评分不一致”被拒——36.4 实测时看 `good_passed` 的失败原因，属于用例评分不合理就改用例，属于 critic 问题就记下来。
- **下一步**：36.3 批改评估集：`evals/grader.py`，用例组成 `ExerciseBody` + `Response`（`formats` 里的 response 模型），走 `grader.grade_messages` → `exercise_grade`（`grader.TASK`）→ `grader.verdict`；指标判对率 + 其他错误语法点命中。可照 `evals/critic.py` 和 `tests/unit/test_evals_critic.py` 的写法。
- **踩坑**：YAML 1.1 里裸写的 `on` / `yes` 会读成布尔值，选项要加引号（格式校验会拦下）。

---

## 2026-10-02 · 任务 36.1 完成（评估框架）

- **做了什么**：建 `backend/evals/`：数据集 YAML（`thresholds` + `cases`）、报告（每条用例若干指标的对错）、录制 / 回放模型（键 = 任务 + 消息 + 输出结构的哈希，对不上抛 `CassetteMiss` 提示重录）、真实模型走 `get_structured_llm` 并可录制、`python -m evals` CLI（`--live --email`、`--record`）、`make eval` / `make eval-live`、pytest 回放（`testpaths` 加 `evals`）、mypy 覆盖 `evals`（Makefile 和 CI）。单测 15 个；pytest 1144 全过。
- **未完成**：`evals/registry.py` 的 `EVALUATORS` 还是空的；`evals/datasets/`、`evals/cassettes/` 没有文件。
- **下一步**：36.2 critic 数据集与评估器。评估器实现 `runner.Evaluator`（`name` + `run_case(case, model)`），用 `model.structured(case.id, "exercise_critic", drafts.critic_report_model(rules), critic_messages(...))` 拿报告，再 `drafts.judge`；登记到 `EVALUATORS`。用例里的题目要能组成 `ItemBrief`（看 `inputs.ItemBrief` 的字段）和 `ExerciseBody`（`formats.parse_body`）。录制要到 36.4 才有，之前回放会因 `CassetteMiss` 失败——36.2/36.3 用单测里的假模型验证评估器逻辑，`test_replay.py` 在录制入库前要能跳过没有录制文件的数据集，或者 36.2 先不登记到 `EVALUATORS`，到 36.4 再登记。
- **踩坑**：argparse 的 `nargs="*"` 配 `choices` 在没给参数时会报错，改为手动校验名字。

---

## 2026-10-02 · 任务 36 已拆分（最小评估集），未开工

- **做了什么**：把任务 36 拆成 36.1–36.4，写进看板。Q36a–d 按推荐确认：a 回放按“任务 + 消息和结构的哈希”对，对不上就失败并提示重录；b 真实模型用开发库里指定账号租户的连接，走 provider 层；c 门槛是坏题拒 ≥ 90%、好题过 ≥ 90%、批改判对 ≥ 90%，写在数据集文件里；d 回放模式跟 pytest / CI 一起跑。用户决定：产品做完整之前不再逐个任务手工实测，每个功能用 E2E 覆盖主流程。
- **未完成**：36.1–36.4 都没动代码，`backend/evals/` 还不存在。
- **下一步**：做 36.1。
  - 要接入的入口：critic 是 `app/adaptive/exercise/messages.py` 的 `critic_messages` → `drafts.critic_report_model` → `drafts.judge`；批改是 `grader.grade_messages` → `Graded` → `grader.verdict`。
  - 真实模型从 `app/providers/llm.py` 的 `get_structured_llm(ctx, task, schema)` 走，`ctx` 是 `TenantProviderContext`，需要按账号从开发库加载。
  - pytest 的 `testpaths` 目前只有 `tests`（`backend/pyproject.toml`），要把 `evals` 加进去（Q36d）。
- **踩坑**：无。

## 2026-10-02 · 任务 50 完成（测试提醒）

- **做了什么**：拆成 50.1–50.6，Q50d–g 按推荐确认。50.1 `advice/reminder.py`（`decide` / `load` / `current`，规则 `2026-10-02.4`）；50.2 `reminder_dismissals` + 迁移 `72f41c4740dd`、`GET /placement/reminder`、`POST /placement/reminder/dismiss`；50.3 建议候选改用提醒（`retest_progress` 0.75）、`describe` 按原因、`daily.md` 第一条回复带原因提一次、被搁置的 `GET /advice` 不给页面；50.4 `components/placement/placement-reminder.tsx`，引导条改用它，删掉 `bannerFor`、`usePlacementBannerClosed`、`retest_due`；50.5 练习落地页（never / resume，练习页专用文案）和汇总（progress / age）；50.6 E2E `placement-reminder.spec.ts`、文档、Docker。make lint 干净，pytest 1129、Vitest 315、E2E 46 全过。
- **未完成**：无。Docker 全栈实测过（临时账号造出没测过、满 60 天、B1 学会 24/33 三种情况，接口、看板建议卡片、聊天页引导条（含手机宽度）、练习页、以后再说后刷新都对；测完删了账号和它的 tenant）。已推送到 8ce05ef，CI run 37007769203 四个 job 全绿。
- **真实模型实测**（用户临时提供的 OpenAI 兼容连接，测完账号、租户和连接都已删除）：看板“今天学什么？”第一条回复带原因提重测并给“去测试”卡片；点“以后再说”后页面只剩“选词书”，私教继续给建议时不再提测试、不出卡片；学习者自己问起时私教给“去测试”卡片。
- **下一步**：用户实测提醒（可以在 `/learner` 看哪一级学会了多少，或在开发库里把一个测试的 `finished_at` 往前改 60 天看 age 提醒）；然后回到 P2 看板下一个任务。
- **踩坑**：① 练习页测试用 `api.mockResolvedValueOnce` 按顺序排队，新组件多一次请求就会打乱队列，所以在测试里单独 mock `@/lib/placement` 的两个函数。② next-intl 的 `t()` 不接受拼出来的 key，要写成明确的字面量。③ 手工往库里插 `placement_sessions` 造测试时，`user_profiles.cefr_level` 不会跟着写（正式交卷才写回），看板顶部会显示“未评估”，不是 bug。④ 规则文件改任何东西都要升 `version`，会让所有学习者的掌握度在下次读取时重放一次、预生成的练习组过期。

## 2026-10-02 · 任务 35 完成（练习接口、练习页、入口）

- **做了什么**：35.1–35.5 见看板（指定语法点的组、继续没做完的组、开组掌握度快照；`api/practice.py` 五个接口；学习者模型“学会的条件”；`/practice` 页；“做一组题 / 对话练习”入口）。35.6：`fake_llm.py` 加出题、审题、批改的假回复，新 `frontend/e2e/practice-set.spec.ts` 两个流程，`practice.spec.ts` 改按钮名；修了 E2E 发现的 500（见踩坑）；`docs/agent-tools.md`、P2 计划落地记录。make lint 干净，pytest 1110、Vitest 311、E2E 45 全过；Docker 重建，迁移 head `27b21e3b464b`。
- **未完成**：无。已推送到 502a355，CI run 36998731468 四个 job 全绿。
- **下一步**：新会话开始任务 50（测试提醒，Q50a–c 已确认），开工前先拆子任务。
- **踩坑**：① `answering.answer()` 在批改前 rollback、结束后 commit，`report()` 也 commit，之后依赖注入的 `user` / `tenant` 对象过期，接口里再读 `user.id` 会触发同步懒加载（async 下报 `MissingGreenlet` → 500）；要在调用前把 id 取出来。② 上一个会话因为对话累积超过 32MB 请求上限而中断（大量 E2E trace / 输出），跑 E2E 时只 tail 结果，不要把 trace 内容读进对话。③ 等后台进程时不要用 `pgrep -f`，它会匹配到自己的 shell。

## 2026-10-02 · 任务 34 完成（批改）

- **做了什么**：34.3 `adaptive/exercise/answer.py`：`answer()`（代码判 / 模型判 → `attempts` + `kc_evidence` → `mastery.refresh` → 组状态）和 `report()`（标 `reported`、删证据重放、保留作答），都自己提交；`worker.structured_call` 抽出来供批改复用。34.4 同文件 `_update_ability`：每次计入的作答走一步 Elo，没有记录时从等级锚点起步。34.5 文档：agent-tools、ADR 0021 §6、P2 计划。集成测试 15 个，pytest 1075 全过，ruff、mypy 干净。提交 1d3492e、6062901 和本条。
- **未完成**：无。任务 34 全部完成；已推送到 ba2402e，CI run 36983190564 四个 job 全绿。
- **下一步**：任务 35（练习页与接口），开工前先拆子任务。接口要点：`worker.start()` 拿 set id，`stage()` 给进度；作答调 `answer.answer(..., grade_call=worker.structured_call(ctx, config, "exercise_grade"))`，`config` 带 `metadata.user_id`，这样 `llm_usage` 能记到人；`Answered.set_done` 或 `report()` 返回 True 时调 `practice_worker.prefetch(user_id, tenant_id)`；异常映射：`ExerciseNotFoundError` → 404，`NotAnswerableError` → 409，`InvalidResponseError` → 422，`GradingFailedError` → 503（请重交）；`exercises.answer` 只在作答后返回。前端挂 `practice_set`、`practice_grade` 的 AiBadge。
- **踩坑**：① `answer()` 在模型调用前 `session.rollback()` 结束读事务，所以调用方不能在同一个 session 里留着没提交的写入。② 同一学习者对**不同**题并发作答、且还没有 grammar 能力记录时，两边可能同时插入 `skill_estimates`，会撞主键；练习页是一题一题交的，暂不处理。③ 举报不回退 Elo，ADR 0021 §6 已写明。

## 2026-10-02 · 任务 34.1、34.2 完成

- **做了什么**：34.1 `exercise/grading.py` 代码批改（17 个单测，提交 78b0272）。34.2 `exercise/grader.py` + `prompts/exercise_grade.md`：结构化输出 `Graded`（`correct`、`explanation`、`corrected`、`other_mistakes`），`grade_messages(body, kc, response, explain_in)`，`verdict()` 丢掉目标 KC、清单外 KC、空原文、重复；`features.yaml` 的 `practice_grade`（`exercise_grade` 走默认路由）+ 前端 `ai-usage.ts` 和中英文案。pytest 1060 全过，ruff、mypy、tsc、vitest 干净。提交 b17f261。
- **未完成**：34.3–34.5 未开始。
- **下一步**：34.3 作答服务 `exercise/answer.py`。模型调用仿照 `worker.model_calls`：`get_structured_llm(ctx, "exercise_grade", Graded)`，失败时不存作答（Q34d）。find_fix 只有位置对、改法不在列表里时才调模型（`grading.grade` 的返回值告诉你要不要）。
- **踩坑**：① 上一次会话因请求超过 32MB 中断，34.2 的两个文件是那时留下的未提交文件。② 语法点清单让系统提示词约 7k token，所以用量默认估 7500 输入。③ `frontend/node_modules/.bin/*` 是 shell 脚本，不能用 node 直接跑，要跑 `node_modules/vitest/vitest.mjs`、`node_modules/typescript/bin/tsc`。

## 2026-10-02 · 任务 33 完成（Q33g 已定），提出任务 50

- **做了什么**：Q33a–f 按推荐确认。33.1 `exercise/inputs.py`（`load` / `plan_set` / `briefs`，含个人档案和讲解语言）；33.2 `exercise/drafts.py`（扁平 schema、`to_body`、`judge`）、`exercise/messages.py`、两个提示词、`rules.yaml` `2026-10-02.3`（`critic_max_gap`、`bank_repeat_days`、`min_items`、`prefetch_max_hours`）、providers 两份 YAML 加 `exercise_critic` 路由、`features.yaml` 的 `practice_set` + 前端文案；33.3 `exercise/bank.py`；33.4 `agents/exercise_graph.py` + `exercise/service.save_result`；33.5 `exercise/worker.py` 的 `PracticeWorker`（接进 `main.py`）、迁移 `9f45cf7f00b8`（开发库已升级）、`service.how_made`。pytest 1030 全过，ruff、mypy、tsc 干净。5 个提交未推送（加上任务 32 共领先 origin 约 15 个）。
- **Q33g 后续**：用户按推荐确认，题库补位加第四档（等级范围内其他薄弱语法点，按选题优先级）；`planner.candidates()` 从 `plan()` 拆出，`inputs.wider_kcs()`、`bank.fill(wider_kcs=)`、`ExerciseContext.wider_kcs`。33.6 文档完成（agent-tools、ADR 0021、P2 计划、PLAN）。pytest 1036 全过。
- **未完成**：任务 50（测试提醒，用户提出：没测过、学到一定阶段的人，私教要及时提醒）的子任务和 Q50a–c 待用户确认；现状和缺口写在看板任务 50。
- **下一步**：等用户确认 Q50a–c；然后拆任务 34（批改）。任务 34/35 结束一组时要调 `app.state.practice_worker.prefetch(user_id, tenant_id)`；API 用 `start()` 拿 set id、`stage()` 给进度、`service.how_made()` 给公示。
- **踩坑**：① `Result.tuples()` 在 SQLAlchemy 2.1 已弃用，用 `.all()`。② pytest 会把测试文件里名为 `test` 的辅助函数当用例收集。③ 带标签联合（oneOf / discriminator）不能直接作结构化输出 schema，各家支持不一。④ 没入学测的新学习者按 A2 算，A2 窗口里多数语法点先验 p ≥ 0.4，所以第一组几乎全是产出题（transform / translate），这是 Q32d 的结果，实测时留意体验。

---

## 2026-10-02 · 任务 32 完成

- **做了什么**：Q32a–d 按推荐确认（学会后对话 / 写作再错记 Again；p 跌破 weak 撤销学会、进度清零；候选 = 等级窗口 −2…+1 + 有证据的，没入学测按 A2；先识别后产出），写进 ADR 0021。32.1 `rules.yaml` 版本 `2026-10-02.2`，`practice` 加选题参数。32.2 `app/adaptive/learned.py`：从证据重放“学会”与 FSRS，第一次复习评 Easy，每组练习一次复习。32.3 `mastery.refresh` 连 attempts → exercises 拿练习组，写新列。32.4 `app/adaptive/exercise/planner.py`：`plan()`。pytest 959 全过。
- **未完成**：无。`frontend/Dockerfile` 可选代理构建参数仍未决。
- **下一步**：任务 33 出题子图（generate → critic → 重生成 → 题库兜底 + 后台预生成下一组）。开工前拆子任务，需要定的点：调用 `plan()` 时组装 `KCState` 的查询（`recent_mistakes`、`has_own_sentence` 从 `kc_evidence` 算，`ability` 取 `skill_estimates` 的 grammar）；`exercise_generate` / `exercise_critic` 的提示词和结构化输出（输出直接用 `formats.py` 的模型，`rewrite_own` 的 `evidence_id` 由代码填）；题库兜底从 `placement/items.yaml` 按 KC 和难度挑 choice4；`features.yaml` 登记 `practice_set`；`docs/agent-tools.md` 和 providers YAML 加新 task 的默认路由。
- **踩坑**：① 练习答错的证据必须带计入的严重度（照入学测写 `wrong_choice` / `medium`），否则 `bkt.counted` 会丢掉它（任务 34 要注意）。② 数据库读出的时间带会话时区，py-fsrs 只收 UTC。③ 现有 BKT 参数下，从 0.05 起答对三次（含一道产出题）就到 0.975，光看 p 判“学会”太快，这也是门槛要加题型和跨天的原因；P2 实测时再看要不要调 `p_learn`。④ 会话里还挂着的 ORM 对象会被 `update()` 同步改掉，测试里先取值再改。

## 2026-10-02 · 任务 30 收尾 + 任务 31 完成

- **做了什么**：用户 review 通过任务 30。任务 31 拆成 31.1–31.4，Q31a–c 按推荐确认（语法点 FSRS 从证据重放；“没再错”= 前 14 天对话和写作里没有计入错误；“跨天”= 答对首末相隔 ≥ 20 小时，不按自然日），写进 ADR 0021 §7。31.1 `app/adaptive/exercise/formats.py`（六种题型的 Pydantic 模型、`parse_body`、`parse_response`、`normalize`、`SPECS` 写明判法和证据类型）。31.2 `rules.yaml` 版本 `2026-10-02.1`：`guess_by_format` 补齐，新增 `practice`、`mastery_gate`；`rules.py` 对应模型。31.3 迁移 `3b9536dae2f6`：`exercise_sets` / `exercises` / `attempts`，`kc_evidence` 加来源、`format`、`attempt_id`，`kc_mastery` 加“学会”进度和 FSRS 列；开发库已升到这个版本。31.4 pytest 880、ruff、mypy 全过。
- **未完成**：无（任务 31 全部完成）。`frontend/Dockerfile` 可选代理构建参数仍未决。
- **下一步**：任务 32：先拆子任务写进看板。要点：`bkt.replay` 的 `Observation` 加 format 和 source，重放时算 `formats_passed`、`correct_span_hours`、`last_mistake_at`（只算 chat / writing 的计入错误）、`mastered_at`，之后的练习证据按 Good / Again 交给 FSRS（复用单词的 `fsrs` 参数），写回 `mastery.refresh`；find_fix 一次作答产生两条证据，per-turn 上限要按 `attempt_id` 分组；选题优先级权重要加进 `rules.yaml`（再升版本号）；选题纯函数放 `adaptive/exercise/planner.py`。
- **踩坑**：`rules.py` 不能引用 `exercise/formats.py`（循环引用），“每种题型都有猜中率”放在测试里检查。ruff 的 RUF001 不允许字符串里直接写弯引号，用码点写。

## 2026-10-02 · P2 Q5–Q13 确认 + 任务 30 ADR

- **做了什么**：Q5–Q13 全部按推荐确认，写回计划 §10 和看板（提交 734e01f）。任务 30：写 ADR 0021（练习引擎）、0022（图谱存 Postgres）、0023（Supervisor 与 coach）、0024（阅读来源与版权）、0025（定时任务与后台上限）；ADR 0001 标注被取代部分；PLAN 全面同步（去掉 Neo4j、interrupt、VOA）；compose 删 neo4j 服务和卷，`.env.example` 删 `NEO4J_*`，CLAUDE.md 和 `kc/catalog.py` 注释同步。
- **D3 修订**：核实发现 VOA Learning English 的 RSS 全停在 2025 年 3–4 月、只有摘要；Wikinews 已关闭；The Conversation 是 CC BY-ND（不能改写）。用户改定内置 NASA 新闻稿（公有领域，RSS 带全文）+ Global Voices（CC BY 3.0，RSS 带全文，跳过 NC-ND 转载）+ 自加 RSS。
- **未完成**：任务 30 等用户 review ADR（看板里列了我按推荐定的细节）后标 [x]。`frontend/Dockerfile` 可选代理构建参数仍未决。
- **下一步**：用户 review 通过 → 任务 30 标 [x] → 任务 31（数据表与迁移 + 题型定义 + `rules.yaml` 新参数），开工前先把 31 的子任务写进看板。
- **踩坑**：本地如果用过 `--profile neo4j`，会留下孤立的 `neo4j-data` 卷，需要手动 `docker volume rm`。

## 2026-10-02 · P2 计划与任务拆分

- **做了什么**：推送任务 29 到 86f065e，用户实测一轮通过，P1 收尾完成。用子 agent 摸清了 P2 相关现状（见下“现状要点”），写了 `docs/plans/P2-adaptive-reading-writing.md`（Demo 定义、五个子阶段、依赖、练习引擎 / Supervisor 与写作 / 阅读与定时任务 / 图谱与诊断 / 每日计划、表汇总、任务顺序、决定）。用户已确认 D1–D4：顺序 练习引擎 → 写作 → 阅读 → 图谱诊断 → 每日计划；语法图谱存 Postgres（不用 Neo4j）；阅读来源 VOA Learning English + 自加 RSS；Supervisor 按原计划。看板 P2 段拆成任务 30–49，原“后台预生成 AI 例句”并入任务 44。
- **现状要点**（开工时不用再查）：对话图 `agents/chat_graph.py` 是 `load_context → tutor ⇄ tools`，`MAX_TOOL_ROUNDS=2`；会话分支在 `api/chat.py::_reply`（`focus_kc_id` 练习无工具、`purpose` planning/daily 有限工具、自由对话全部工具）；`kc/grammar.yaml` 119 个 KC，约 109 个有 `prerequisites`，`catalog.py` 已校验无环；`kc_evidence.source` 只有 chat / placement（check 约束），没有题型列；`rules.yaml` 的 `elo.guess_by_format` 只有 choice4；入学测 `items.yaml` 90 道 choice4 可作兜底题库；没有题目 / 作答 / critic / APScheduler / `backend/evals`；后台任务可照 `memory/worker.py` 的 `ReflectionWorker`；结构化调用范例 `chat/translate.py`、`memory/reflection.py`、`services/vocab/examples.py`。
- **未完成**：Q5–Q13（计划 §10，题型范围、开放题判对、出题时机、题目复用、Supervisor 路由、写作入口、每日计划确认方式、后台调用上限、评估集）还没和用户确认；ADR 0021–0025 未写（任务 30）。`frontend/Dockerfile` 可选代理构建参数仍未决。
- **下一步**：新会话：① 和用户确认 Q5–Q13，结果写回计划 §10 和看板；② 任务 30（ADR + PLAN 同步 + 删 neo4j profile）；③ 任务 31 起按顺序做，开工每个任务前把子任务写进看板。
- **踩坑**：无新坑。

## 2026-10-02 · 推送任务 28，任务 29 猫咪动画

- **做了什么**：推送 28 个提交到 4b9b324，CI run 36905913966 全绿。用户放入 `docs/design/lingo-cat-motion/`（logo 猫六种情绪），拆成任务 29，Q29a–d 已确认（头像本身播 ai 动画、所有空状态和错误都用猫、骨架屏保留、done 每次都播）。29.1 设计包入库（删 Zone.Identifier）。29.2 `components/brand/lingo-cat.tsx`（`LingoCat`、`Delayed`、`CatLoading`）+ `lingo-cat.css`（`globals.css` 引入），i18n `cat` 命名空间。29.3 `EmptyState` 去掉 `icon` 改画猫；新增 `ui/error-text.tsx`，替换 20 多处一行错误；对话页 `message-list.tsx` 的 `waiting()` 时头像位置放 ai 猫、不画空气泡；复习完成 / 入学测结果 done；翻译、AI 例句、查词放 16px 猫。29.4 临时截图脚本对照浅色 / 深色 / 减少动态效果，整页失败改为大号 oops；修 `i18n.spec` 偶发冲突。Docker 只重建了前端。
- **未完成**：任务 29 的 5 个提交未推送。hop 动画暂无使用处（现有长等待都是私教对话）。`frontend/Dockerfile` 是否加可选代理构建参数仍未决（本次又用了 `/tmp/frontend.proxy.Dockerfile`，只多 `ENV NODE_USE_ENV_PROXY=1`）。
- **下一步**：① 推送并看 CI；② 用户实测猫咪动画（对话等待、空生词本、复习完成、断开后端看出错）和之前积压的 28–20.5；③ 进入 P2，先拆任务写进看板、和用户确认。
- **踩坑**：zsh 里 `for f in $files` 不按换行拆分，批量改文件改用 Python；`CatLoading` 300ms 内只有带 `role=status` 的空容器，测试要用假计时器；等待态的猫如果绝对定位，桌面上这一行高度为 0，要留在文档流里（`md:-ml-[42px]`）。

## 2026-10-02 · 任务 28 复习卡片例句（Tatoeba + 按需 AI 例句）

- **做了什么**：用户反馈来源只有 ECDICT、没有例句。Q28a–c 按推荐。28.1 ADR 0020。28.2 `word_sentences` 表（迁移 `4d7a2c9e1b60`）+ `services/vocab/import_tatoeba.py` + `make sentences-import`：选句是纯函数 `pick`（生词数 → 与 9 词的差距 → id，句中大写当人名，近似句去重，每词 2 句），繁体用 OpenCC `t2s`；开发库导入 18,221 句，覆盖率牛津 95%、CET4 89%、CET6 76%、GRE 31%。28.3 `CardOut.sentences` / `forms`，`services/vocab/sentences.py`。28.4 `components/vocab/word-examples.tsx`（变形加粗、原句链接、“AI 例句”按钮挂 `AiBadge word_examples`）。28.5 features.yaml / agent-tools.md / README 署名，OpenCC 由 dev 改为正式依赖，E2E 新增复习卡片例句用例（`run_backend.py` 导入 Tatoeba 小样本）。用户要求记录的“后台预生成 AI 例句”在看板 P2。
- **未完成**：无。是否给 `frontend/Dockerfile` 加可选代理构建参数（本机构建要走 7890 代理，现在靠临时 Dockerfile）未决。
- **下一步**：用户 2026-10-02 初步实测任务 28 暂无问题。新会话：① 推送（本地领先 origin 约 27 个提交）并看 CI；② 用户继续实测 27、26、25、24、23、20.5、21、22；③ 决定 `frontend/Dockerfile` 是否加可选代理构建参数；④ 进入 P2，先拆任务写进看板、和用户确认。
- **踩坑**：Tatoeba 导出没有版本号，不能校验固定 sha256，改为打印日期和哈希；Ruff RUF001 不让源码里出现 `’`，用 `\u2019`；E2E 里例句顺序按“生词数”排，小样本词库里 school、bus 都算生词，所以短句排在前面；`i18n.spec.ts` 偶发 strict 模式冲突（`__next-route-announcer__` 和标题同文本）。

---

## 2026-10-02 · 任务 27 AI 标记符号化 + 复习卡片改版

- **做了什么**：用户反馈 AI 标记太大、复习页无脑居中、英文释义没用、评分按钮丑且被长卡片顶下去。Q27a–d 全按推荐。27.1 `AiBadge` 只留 ✦（`ai-pill.ts` 的 `aiMark` / `aiMarkCorner`）。27.2 `src/lib/meanings.ts` 把 ECDICT `translation` 按词性分行，只有领域标签的行（`[计]` 等）进折叠；`definition` 把硬换行的续行接回去（词性用白名单，避免把行首 `place.` 当成词性）。27.3 `components/vocab/word-meanings.tsx` 用原生 `<details>`，默认收起，摘要写“更多 · N 条专业释义 · 英文释义”，英文先显示 3 条，标“来源：ECDICT”。27.4 背面左对齐，卡片区内部滚动，评分栏 `shrink-0` 固定底部。27.5 四个评分做成分段栏（颜色点 + 下次间隔）；后端 `services/vocab/scheduler.py:preview()` 用关掉 fuzz 的 FSRS 算四个评分各自的间隔，`CardOut.intervals`（秒），前端 `formatInterval` 用 `Intl.NumberFormat` unit 格式化。27.6 用真实词条截图对照 1440/390 × 亮暗；E2E 42、Vitest 290、tsc、eslint、pytest vocab 57、ruff、mypy 全过。
- **未完成**：无。
- **下一步**：用户在 Docker 下实测 27、26、25、24、23、20.5、21、22，然后推送看 CI，之后进入 P2。
- **踩坑**：`fsrs.Card()` 不传 `card_id` 会 sleep 1ms 生成 id，预览时传 `card_id=0`。Bash 里 `node` 也可能被 nvm 懒加载函数劫持，先 `unset -f node npm npx pnpm _load_nvm` 再把 nvm bin 放进 PATH。截图对照用的是临时 `e2e/_shots.spec.ts`（mock 队列），用完已删。

---

## 2026-10-02 · 26.13 修复看板双滚动条

- **做了什么**：用户实测反馈看板有两条滚动条、底部超出侧栏。用临时 Playwright 探针在 E2E 环境量出文档高 1607（视口 900），撑高的是语法表格的 `<caption class="sr-only">`：`sr-only` 是绝对定位，往上没有定位祖先，包含块变成整页，于是 `<body>` 也能滚。修复放在外壳 `frontend/src/app/(app)/layout.tsx`：内容区加 `relative overflow-hidden`，以后任何页面里的绝对定位元素都不会再撑高整页。`e2e/dashboard.spec.ts` 加回归断言（文档高度 = 视口）。typecheck、eslint、E2E 42 全过。
- **未完成**：无。Docker 前端已单独重建并替换（健康，空闲内存 53MiB）。
- **下一步**：同上一条：用户实测 26、25、24、23、20.5、21、22，然后推送看 CI，之后进入 P2。
- **踩坑**：Bash 里 `pnpm` 是 nvm 懒加载函数，会无限递归；直接用 `~/.nvm/versions/node/v24.14.0/bin/node node_modules/<pkg>/...` 调 tsc、eslint、playwright（`node_modules/@playwright/test/cli.js`），`.bin/` 下的是 shell 脚本不能用 node 直接跑。Docker 构建时 corepack 要下载 pnpm（build 阶段没有缓存），容器里直连 npm 会拿到自签名证书；`HTTPS_PROXY` 对 Node 自带的 fetch 不生效，要加 `NODE_USE_ENV_PROXY=1`。本次用临时 Dockerfile 副本（只多这一行）+ `docker build --network host --build-arg HTTPS_PROXY=http://127.0.0.1:7890 -t lingo-agent-frontend frontend`，再 `docker compose up -d --no-build frontend`。

---

## 2026-10-01 · 26.12 完成（任务 26 网站改版全部完成）

- **做了什么**：七个登录后页面 1440/390 × 亮/暗对照通过，无需改代码。按用户选择重建 Docker 全栈（健康，空闲内存 backend 67MiB / frontend 54MiB / postgres 85MiB）。README 截图（20.6.1）按用户选择“造一个演示号”：在隔离的 `lingo_e2e` 库起演示后端 :8100 + 假模型 :8101（脚本回复）+ 前端生产构建 :3100，用临时脚本播种演示用户（入学测 A1、牛津 3000 复习 8 张、一段三轮对话含纠错和收词），中英各截首页、对话、看板、背单词四张 1280×800，放 `docs/screenshots/`，README.md 用 en、README.zh-CN.md 用 zh。用户的 `lingo` 库未动。检查结果沿用 26.11（typecheck、eslint、Vitest 280、E2E 42）。
- **未完成**：无。任务 26 已 `[x]`，20.6 / 20.6.1 已 `[x]`。
- **下一步**：用户在 Docker（:3000）下实测新界面和任务 25、24、23、20.5、21、22；然后推送并看 CI；之后进入 P2（先拆任务和用户确认）。
  - 已给用户的实测要点：26 整站亮暗、侧栏折叠、≤760px 底部标签栏与“更多”面板、对话页抽屉、原地确认 / 清空对话框、未登录三页、复习专注模式；25 朗读设置面板（口音、声音、试听、语速，刷新保持），重点验证 25.7 Edge 在线声音约 3 秒退回本地声音；24 中英开关（三处 + 记忆页，下一句生效）、单词气泡（音标、释义、AI 例句、加入生词本）、气泡朗读与“看中文”（二次切换不调模型）；23 看板“今天的学习”（打开不调模型、快捷回复、确认卡、刷新同一段、对话列表）、结果页页内开场；21 换词书 / 设目标的确认卡与撤销、练习卡 / 直达卡、活动里的工具调用；22 各功能点 AI 标记与估计值（默认 → 历史平均）；20.5 静音拦截、正常转写、连接卡片按能力测试。
  - 2026-10-01 19:46 WSL 中断已查明：Microsoft Store 自动把 WSL 更新到 3.0.1，虚拟机正常关机，不是 Docker 或内存问题，无需处理。
- **踩坑**：已登录用户访问 `/`、`/login`、`/register` 会被重定向，截首页要不带登录态。storageState 里没有 `NEXT_LOCALE` cookie 时按 Accept-Language 选语言，Playwright `locale: "en-US"` 即可截英文界面。对话截图要带 `?c=<会话 id>`，否则是空的新对话。`frontend/.next` 是指向 :8100 构建的，本地要用时重新构建。临时脚本 `_shots.mjs`、`_demo_seed.mjs` 已删除、未提交。

---

## 2026-10-01 · 26.11 完成（首页介绍、登录、注册）

- **做了什么**：新增 `frontend/src/components/home/landing.tsx`（未登录首页，全静态）、`components/ai-pill.ts`（AI 胶囊样式，`ai-badge.tsx` 改为导入它）；`app/page.tsx` 只渲染 `Landing`；`(auth)/layout.tsx`、`auth-form.tsx` 按 login/register 设计稿改版；messages `home` 命名空间重写（demo / features / trust / footer）；`e2e/i18n.spec.ts` 标题断言改为 “Your AI English tutor”，语言切换用 `.filter({ visible: true })`。typecheck、eslint、Vitest 280、E2E 42 全过。
- **未完成**：无（26.11 已 `[x]`）。
- **下一步**：26.12 收尾（全量 E2E、各页 1440/390 亮暗截图对照、Docker 重建先问用户、README 截图 20.6.1）。
- **踩坑**：服务端组件从 "use client" 模块导入非组件常量（如 class 字符串）拿到的是客户端引用，样式会丢——放到普通模块里。首页有两个语言切换（按断点各隐藏一个），E2E 按标签定位要过滤可见。Bash 里 `node`/`pnpm` 被 nvm 懒加载函数遮蔽，用 `$HOME/.nvm/versions/node/v24.14.0/bin/` 绝对路径。截图脚本 `frontend/e2e/_shots.mjs` 仍不提交。

---

## 2026-10-01 · 26.10 完成（设置页改版已提交）

- **做了什么**：设置页改版：`settings/settings-app.tsx`（宽屏右侧粘性目录、窄屏顶部横向标签，滚动高亮当前区块；路由分主卡 + 三张紧凑卡）、`connections-section`（地址 / 密钥 / 最近测试三栏，编辑删除改幽灵按钮，添加表单两列）、`route-section`（`compact`，序号 + “备用”标签，模型名 `data-slot="route-ref"`）、`usage-section`（表格等宽、合计行、空状态）；messages 增 `settings.toc`、`settings.route.fallback`、`settings.connections.address/key/lastTest/lastOk`。E2E `settings.spec` 断言改为 `route-ref` 与“密钥…1234”，`i18n.spec` 改按卡片标题定位。typecheck、eslint、Vitest 280、E2E 42 全过。
- **未完成**：无（26.10 已 `[x]`）。
- **下一步**：26.11 首页产品介绍页、登录、注册（对照 `docs/design/lingo-agent-design/screens/` 下 landing / login / register）→ 26.12 收尾（全量 E2E、亮暗截图、Docker 重建先问用户、README 截图 20.6.1）。
- **踩坑**：路由列表项文字现在包含序号和“备用”，测试要断言 `[data-slot="route-ref"]`；“模型连接”同时出现在目录和卡片标题，按文字查找要限定范围。截图脚本 `frontend/e2e/_shots.mjs` 仍不提交。

---

## 2026-10-01 · 26.10 背单词、入学测已提交，设置进行中

- **做了什么**：背单词四页 `fc287de`；入学测改版已提交（`placement/placement-app.tsx`、`placement-result.tsx`、`placement-tutor.tsx` 对话框浅底、`vocab/placement-known.tsx` 的 `bare`；messages `placement.intro/question` 改键；`e2e/helpers.ts` 的 `answerOne` 用 “/” 判断词汇阶段）。typecheck、eslint、Vitest 280、E2E 42 全过。
- **未完成**：设置页 `settings/settings-app.tsx`、`connections-section`、`display-section`、`read-aloud-section`、`route-section`、`usage-section` 对照 `screens/settings-desktop-*`、`settings-mobile-*` 改样式；提交后 26.10 标 `[x]`。
- **下一步**：设置页 → 26.11 首页介绍、登录、注册 → 26.12 收尾。
- **踩坑**：截图脚本 `frontend/e2e/_shots.mjs` 未跟踪，不要提交（用法见文件头，mock 结果页用 `/tmp/pr.json`）；dev 服务器 3001/8100/8101 结束前 `fuser -k` 停掉。

---

## 2026-10-01 · 任务 26.9 完成，26.10 背单词进行中

- **做了什么**：26.9 看板、学习者模型、记忆三页改版，已提交 `e61218d`、`0f8663d`、`1d302eb`（Vitest 280、E2E memory/language 通过）。26.10 背单词首页 `vocab/vocab-app.tsx` 已重写（今日卡片大字计数 + 开始按钮、熟词筛选提示改 Callout、词书行进度条/“还没开始”、每日新词步进器），messages 新增 `today.countsMain/countsStarted`、`books.notStarted`、`dailyNew.fewer/more`，删 `today.counts`；typecheck、eslint、vocab-app.test 通过，**未提交**。
- **未完成**：`vocab/mine-app.tsx`、`screen-app.tsx`、`review-app.tsx`、`placement-known.tsx` 改样式；全量 Vitest + `e2e/vocab.spec.ts`；之后入学测（`placement/*`）、设置（`settings/*`）各提交一次。
- **下一步**：对照 `screens/vocab-mine-*`、`vocab-screen-*`、`review-*` 改完背单词四页，截图核对后提交。
- **踩坑**：截图脚本 `e2e/_shots.mjs` 已删，需要时按上次的写法重建（base :3001、storageState `/tmp/shot-state.json`、zh-CN），不要提交；dev 服务器 3001/8100/8101 结束前用 `fuser -k` 停掉。

---

## 2026-10-01 · 任务 26.8 对话页完成，26.9 开工

- **做了什么**：26.8 对话页改版（会话列表分组 + 手机抽屉、消息气泡、输入区、私教卡片），typecheck、eslint、Vitest 280、E2E 42 全过，已提交 `3f7a85a`（ahead 7，未推送）。E2E 里“会话列表”从 list 改成 navigation。
- **未完成**：26.9（看板、学习者模型、记忆三页 + 空状态）标 `[~]`，尚未改代码。要改的是 `frontend/src/components/dashboard/*`、`learner/learner-app.tsx`、`learner/kc-item.tsx`、`memory/memory-list-section.tsx`、`memory/profile-section.tsx`。
- **下一步**：对照 `docs/design/lingo-agent-design/screens/{dashboard,learner,memory}-*.jpg` 和组件规格 §2/§10–§16，用 26.5 的通用组件（Tag/CefrTag、ProgressBar/StackedBar、EmptyState）改样式，保留 test id 和 aria 名称。
- **踩坑**：截图脚本参数是 JSON 字符串，不是文件路径（用 `"$(cat /tmp/s.json)"`）；Docker 前端镜像还是 26.x 之前的，26.12 统一重建。

---

## 2026-10-01 · 任务 26.2–26.7：设计包收入、视觉基础、外壳、确认方式

- **做了什么**：设计包收入 `docs/design/lingo-agent-design/`（截图压成 1100px JPEG），26.3 拆成 26.4–26.12，Q26a–f 按推荐确认。26.4 token / 字体 / logo / 主题（ADR 0019）；26.5 写死颜色换 token、AiBadge 重做、通用组件（tag / progress / callout / status-text / empty-state）；26.6 侧栏 + 手机顶栏 / 底栏 / “更多”面板（`components/shell/`、`ui/sheet.tsx`）；26.7 `ui/confirm-dialog.tsx`、`ui/inline-confirm.tsx` 替换全部 `window.confirm`。每步 typecheck、eslint、Vitest 277、E2E 42 全过并已提交（ahead 6，未推送）。
- **未完成**：26.8 对话页（看板标 `[~]`），尚未改代码；之后 26.9–26.12。
- **下一步**：按 `docs/design/lingo-agent-design/` 组件规格“对话页”改 `frontend/src/components/chat/` 下各组件；手机会话列表用 `Sheet side="left"`。保留现有 test id 和 aria 名称（E2E 依赖“会话列表”“新对话”）。
- **踩坑**：截图要先删 `/tmp/shot-state.json`（e2e 库重置后旧会话失效）；dev 截图右下黑色 “N” 是 Next 开发指示器；WSL 中文字体靠 `~/.local/share/fonts` 里软链的微软雅黑（用户级，不在仓库）。

---

## 2026-10-01 · 任务 25 收尾、推送、任务 26.1 设计提示词

- **做了什么**：
  - 用户决定 25.4（服务端朗读）、25.5（单词发音预生成）移到 P3 作为后续优化项，任务 25 标完成；MeloTTS 作为未实测的自部署候选记在 P3（没测过，之前测的是 MOSS-TTS-Nano）。
  - README 中英“还没做”里服务端朗读改为 P3（12eec2c）。
  - 推送 29 个提交到 origin/main（7dcbf86..12eec2c），CI run 36827696611。
  - 新增任务 26（网站视觉改版）。26.1：`docs/design/claude-design-brief.md`，给 Claude Design 的完整提示词。页面元素盘点由只读代理逐页读组件和 `messages/zh-CN.json` 得出。
- **未完成**：26.2 等用户出设计；26.3 拿到资源后拆任务。CI：run 36827946208（eaaa49b）四个 job 全绿；前一个 run 36827696611 的 e2e 是被新推送的 `cancel-in-progress` 取消的，不是失败。
- **下一步**：用户把设计资源同步到本地后，读 `tokens.css` / 设计稿，拆 26.3 的子任务给用户确认。
- **踩坑**：现状要点都写在设计提示词末尾的“附：现状参考”里：只有浅色、没有深色切换（`next-themes` 已装未用）、写死的 violet / emerald / amber、移动端没有适配、`public/` 没有品牌资源、中文字体没设置。

---

## 2026-10-01 · 任务 25.7：在线声音播不出时退回本地声音

- **背景**：用户实测 Edge，下拉里的 Online (Natural) 声音都没声音，只有本地的三个能用；Edge 自己的“大声朗读”也没声音，确认是连不上微软语音服务。Chrome 的 Google 声音同理。
- **做了什么**：
  - `frontend/src/lib/voices.ts`：`usable()` 排除名字带 `undefined` 的（Edge 150 已知问题）；`isOnline()`；`VoiceChoice.failed`，`pickVoices` 先去掉失败的声音（手动选的也去掉）。
  - `frontend/src/lib/speech.ts`：`Utterance.kind`；纯函数 `revoice()`；`play()` 取代原来的直接排队：全部排进浏览器队列，按 `onstart` / `onend` / `onerror` 逐句跟踪，在线声音 3 秒（`ONLINE_START_TIMEOUT_MS`）没开始、或没开始就结束 / 报错 → `markFailed()`，取消并从这一句用 `revoice()` 重排；`session` 计数让被取消的事件失效（`stopSpeaking` 也 `session++`）；`useFailedVoices` / `useFellBack`。失败记录只在当前页面（Q25g）。
  - `reply-tools.tsx` 提示 `chat.reply.fellBack`；`speech-settings.tsx` 给失败的声音加“（这台设备上播不出声）”，并显示 `speech.silentHint`。
  - 测试：`lib/speech-fallback.test.ts`（假定时器，`vi.resetModules` 每个用例重新加载模块）、`voices.test.ts` / `speech.test.ts` 新用例、`e2e/speech.spec.ts` 新增“在线声音没声音”用例（假设备逐句播放，`silentOnline` 时在线声音永远不开始）。Vitest 275、E2E 42 全过。
  - ADR 0018 §1 补充退回规则。
- **未完成**：Docker 重建后用户在 Edge 上再实测：第一次朗读会有约 3 秒静音，然后由本地声音接着读；之后本页直接用本地声音。
- **下一步**：等用户实测；之后决定 25.4 / 25.5 或进入 P2。
- **踩坑**：失败退回时只换掉失败的那个声音，排在后面、还没轮到的其他在线声音（比如中文的 Xiaoxiao）仍会各自试一次，所以中英都是在线声音时，最坏会各等一次 3 秒。

---

## 2026-10-01 · 任务 25.6：朗读 E2E、README、Docker 重建

- **做了什么**：
  - `frontend/e2e/speech.spec.ts`：无头 Chromium 没有声音，用 `addInitScript` 替换 `speechSynthesis` / `SpeechSynthesisUtterance`，模拟声音列表并把朗读内容记到 `window.__spoken`。覆盖：没有中文声音时只读英文并提示、优先 Natural 声音、默认语速 0.9；设置页选英音 / 中文声音 / 语速，试听生效，刷新后保留。E2E 全量 41 通过。
  - README 中英：朗读说明（自动挑声音、设置 → 朗读）、“还没做”改为可选服务端朗读和单词发音预生成（ADR 0018）。
  - `make up` 约 27 秒（只重建前端），镜像里已有新代码，backend 健康检查 200。
- **未完成**：用户在真实浏览器（Edge / Chrome / Safari / 手机）里实测朗读：声音是否挑对、中英切换是否自然、设置面板布局（齿轮弹出框 `w-80`）。25.4（服务端朗读连接）、25.5（单词发音预生成）按 Q25f 等实测后再定。
- **下一步**：等用户实测反馈；之后决定 25.4 / 25.5，或进入 P2。
- **踩坑**：Playwright 里可以用 `Object.defineProperty(window, "speechSynthesis", …)` 覆盖浏览器自带的朗读对象；真实的 `utterance.voice` 只接受真正的 `SpeechSynthesisVoice`，所以 `SpeechSynthesisUtterance` 也要一起替换。

---

## 2026-10-01 · 任务 25.3：朗读设置面板

- **做了什么**：
  - `frontend/src/components/speech/speech-settings.tsx`：口音、英文声音、中文声音（下拉第一项是“自动（当前：挑中的声音）”，按另一项的当前设置计算）、试听、英文语速；没有中文声音时提示并禁用中文试听；浏览器还没列出声音时禁用下拉并说明。
  - 入口：设置页“朗读”卡片（`components/settings/read-aloud-section.tsx`，接在“显示”后面）+ 私教气泡朗读按钮旁的齿轮（`reply-tools.tsx`，Popover）。
  - `frontend/src/lib/speech.ts`：设置存 `localStorage` 的 `lingo.speech`（JSON，`parseSpeechSettings` 校验和夹取范围；存储不可用时只在本页生效），`useSpeechSettings` / `useVoices` / `speakSample`；`useCanSpeak` 同时订阅声音和设置。
  - 测试：`components/speech/speech-settings.test.tsx`（5 个）+ reply-tools 齿轮用例；Vitest 268 全过，eslint / tsc 干净。
- **未完成**：25.6（E2E：没有声音时的提示、设置保存；README 中英；Docker 重建交用户实测）。界面还没在真实浏览器里看过。
- **下一步**：25.6。25.4、25.5 等用户实测 24 和 25 的浏览器朗读后再定（Q25f）。
- **踩坑**：
  - `useSyncExternalStore` 的快照在“不能朗读”分支返回新的 `[]` 会无限重渲染，要返回同一个常量。
  - 本页的设置备份只能在 `localStorage` 抛错时用，否则清掉存储后还会读到旧值。

---

## 2026-10-01 · 任务 25.2：浏览器朗读挑声音

- **做了什么**：
  - 新增 `frontend/src/lib/voices.ts`：按语言分档（英文：所选口音 > 其他 en；中文：zh-CN/hans > zh-TW/hant > 其他，排除 zh-HK / yue / zh-MO）、按名字打分（Natural/Neural 5、Premium 4、Enhanced 3、Google 2、在线 1、Multilingual 1、Eloquence/eSpeak −5）、排除 macOS 趣味声音、常见声音性别表；`pickVoices()` 支持手动选择（`voiceURI`）、Multilingual 整段一个声音、同性别仅作同分时的次序。
  - `frontend/src/lib/speech.ts`：`splitSentences`（句末标点 + 换行，`.?!` 后需空格；超 200 字按逗号切）、`planSpeech`（没有声音列表时只设 lang；有列表但缺某语言就跳过）、`DEFAULT_SPEECH_SETTINGS`（美音、英文 0.9、中文 1.0）；`speak(text)` 去掉 lang 参数（调用方都只读英文）；`speakSegments` 返回跳过的语言；`useCanSpeak` 订阅 `voiceschanged`。
  - `reply-tools.tsx`：没有中文声音时提示一次（每页一次），i18n `chat.reply.noChineseVoice`。
  - ADR 0018 §1 补充了同性别、无声音列表、语速、切句的实现细节。
  - 顺手修了任务 24.7 留下的 eslint 错误（`e2e/language.spec.ts` 的 `useFakeModel` 别名），单独提交 fc3aa71。
- **未完成**：25.3 设置面板。`speech.ts` 里的 `currentSettings()` 现在固定返回 `DEFAULT_SPEECH_SETTINGS`，25.3 改成从 localStorage 读（参考 `lib/preferences.ts` 的 `useStored` / fallback 写法），并导出声音列表给下拉框用（`englishVoices` / `chineseVoices` 已在 `voices.ts`）。
- **下一步**：25.3。
- **踩坑**：Bash 里 `pnpm` 是 shell 函数，嵌套调用会报 `_load_nvm` / FUNCNEST，要用 `~/.nvm/versions/node/v24.14.0/bin/pnpm` 绝对路径；项目没有 prettier，格式只靠 eslint。

---

## 2026-10-01 · 任务 25.1：ADR 0018 朗读三层方案

- **做了什么**：
  - 新增 `docs/decisions/0018-read-aloud-layers.md`（已采纳）：第 1 层浏览器挑声音（等 `voiceschanged`、按语言筛、按名字打分、Multilingual 整段一个声音、中英同性别、按句切短、没有中文声音只读英文）+ 朗读设置存在 `localStorage`；第 3 层服务端朗读（provider `tts` 任务，兼容 OpenAI `/audio/speech` 或 Azure SSML，按文本+声音+语速缓存，`features.yaml` 的 `read_aloud`）；第 2 层单词发音预生成。第 2、3 层按 Q25f 后定。
  - PLAN：`speech.tts` 改为 `browser`，去掉 Kokoro / edge-tts 默认，语音章节和风险第 4 条指向 ADR 0018；ADR 0017 §5 加修订说明。
- **未完成**：25.2（`frontend/src/lib/speech.ts` 现在只有 `speechSegments` / `speak` / `speakSegments`，没有挑声音，要按 ADR 0018 §1 加纯函数 + 单测）、25.3、25.6；25.4、25.5 待定。
- **下一步**：25.2。现有调用方：`components/chat/word-popup.tsx`、`message-list.tsx`、`reply-tools.tsx`、`vocab/review-app.tsx`。
- **踩坑**：无。

---

## 2026-10-01 · 朗读选型调研，任务 25 改为三层方案并拆分（未开工）

- **做了什么**：
  - 调研 mlx-audio（只支持 Apple Silicon）和 MOSS-TTS-Nano。MOSS-TTS-Nano 在本地实测了内存、速度、容器限额和并发，数字都在看板任务 25 的“调研记录”里。结论：自己跑朗读模型，多用户线上撑不住。
  - 任务 25 改成三层方案：浏览器挑好声音（免费）→ 单词发音预生成缓存 → 可选的服务端朗读兜底。已拆成 25.1–25.6，并列出待确认的 Q25a–f（每条都有建议）。
  - 提交：29cc335、db57164、d7d0851、9843300。
- **未完成**：
  - Q25a–f 用户已确认全按推荐；MOSS-TTS-Nano 不作为方案，只保留本地自部署的建议。
  - 任务 24 等用户在 Docker 下实测，Docker 已重建。
  - 测试环境 `~/bench` 已删除。
- **下一步**：按 25.1（ADR 0018）→ 25.2 → 25.3 → 25.6 的顺序做；25.4、25.5 等 24 实测和 25.2–25.3 用过之后再定。
- **踩坑**：
  - uv 装 torch 要指定 `torch==2.7.0+cpu` 和 PyTorch 的 CPU 源，否则会装上约 5GB 的 CUDA 版。
  - ONNX Runtime 在限制 CPU 的容器里要关掉线程自旋（`session.intra_op.allow_spinning=0`），否则给的核越多反而越慢。
  - 这台机器的 Docker 挂载不了 `~/.local` 下的目录。

---

## 2026-10-01 · 任务 24.5–24.7：单词气泡、气泡朗读与翻译、E2E（任务 24 完成）

- **做了什么**：
  - 24.5：`components/chat/word-popup.tsx`。私教消息的英文单词由 `Markdown words` 的 rehype 步骤包成 `span[data-word]`；悬停 300ms 或点按，弹出词条、音标、朗读、释义、原形、原句、AI 例句和加入生词本。`SelectToAdd` 已删除。朗读函数抽到 `lib/speech.ts`。
  - 24.6：`components/chat/reply-tools.tsx`。朗读把中英文分段，各用对应的声音；“看中文 / 看英文 / 看原文”的译文在气泡原位显示。`ChatMessage.id` 记下后端消息 id。
  - 24.7：新增 `e2e/language.spec.ts`；`fake_llm.py` 支持例句、翻译，问 “which language” 时回报当前语言；README 中英同步；Docker 重建。
  - Vitest 240、E2E 39 全部通过。
- **未完成**：用户在 Docker 下实测任务 24（还有 23、20.5、21、22）；任务 25（服务端朗读）等实测后再拆。
- **下一步**：根据实测反馈修改；没问题就推送、看 CI，再拆任务 25 或进入 P2。
- **踩坑**：
  - 单词包成 span 以后，Testing Library 的 `findByText("整句")` 匹配不到私教消息（文本被拆进了多个子元素）。改用按段落 `textContent` 匹配，见 `today-tutor.test.tsx` 的 `tutorSays`。
  - E2E 没有 `test.use({ locale: "zh-CN" })` 时界面是英文。
  - 会话列表为空时不渲染成 list，不能拿它当页面已加载的标志。

---

## 2026-10-01 · 任务 24.1–24.4：中英比例（前后端）、查词 / AI 例句 / 气泡翻译接口

- **做了什么**：ADR 0017 已采纳（Q24a–j）；24.2 `user_profiles.chat_language` + `app/memory/language.py` + `language_zh.md` / `language_en.md`；24.3 `components/chat/language-switch.tsx`（输入框上方开关、记忆页画像下拉）；24.4 `GET /vocab/lookup`、`POST /vocab/words/{id}/examples`（`services/vocab/examples.py`，按租户 + 词 + 等级缓存）、`POST /conversations/{id}/messages/{message_id}/translate`（`chat/translate.py`，存库），迁移 `7c2e5a91d0b4`、`6a0fc12e79ca`，`features.yaml` 加 `word_examples`、`message_translate`。后端 827、Vitest 221 通过。
- **未完成**：24.5 前端单词气泡（替换 `components/chat/select-to-add.tsx`，`lib/ai-usage.ts` 的 `AiFeature` 要加两项）；24.6 朗读 + 气泡翻译；24.7 E2E（`fake_llm.py` 要能回 `WordExamples` / `Translation`）、README、Docker。
- **下一步**：24.5 → 24.6 → 24.7，然后交用户实测；之后任务 25（服务端 TTS）。
- **踩坑**：Vitest 里 `beforeEach(() => api.mockReset())` 会把返回值当成清理函数导致超时，要写成块语句；ruff RUF001 不让字符串里出现 `’`，用 `\u2019`。

---

## 2026-10-01 · 任务 23.5：E2E、README、Docker 重建（任务 23 完成）

- **做了什么**：
  - E2E：`advice.spec.ts` 改写为看板“今天的学习”全流程（含没配模型的兜底）；`planning.spec.ts` 改为结果页页内开场 + 卡片确认 / 撤销；`practice.spec.ts` 入口改为 `/learner`；`fake_llm.py` 删掉 `AdviceDraft`。全量 36 通过。
  - 修了两个既有 E2E 的不稳定：`dashboard.spec.ts`（看板也有输入框，点“对话”后要等会话列表出现再输入，否则会输进看板的对话框）；`attachments.spec.ts` 录音录到 0:03（假麦克风的蜂鸣是间歇的，1 秒偶尔被静音拦截）。
  - README 中英同步。Docker 全栈重建，健康检查 200。
- **未完成**：用户在 Docker 下实测任务 23（还有 20.5、21、22）；20.6.1 截图等改版后。对话页 `?plan=1` 已没有入口，保留着，以后清理可删 `chat-app.tsx` 的 `planning` prop。
- **下一步**：等用户实测反馈；没问题就推送、看 CI，然后进入 P2 规划。
- **踩坑**：页面上同时有两个“输入消息”框时（看板嵌了对话框），E2E 用 `getByRole("textbox")` 要先确认已经在目标页面。

---

## 2026-10-01 · 任务 23.4：入学测结果页的规划对话框

- **做了什么**：
  - 新增 `frontend/src/components/placement/placement-tutor.tsx`：`PlacementTutor` 替换 `placement-result.tsx` 里的 `NextSteps`，用 `TutorPanel` 嵌入这次测试的规划对话（ADR 0016 §4）。
  - `findPlanning(finishedAt)`：前端从 `GET /conversations` 里挑 `purpose = planning` 且 `created_at >= finished_at` 的最近一段，没加后端接口。
  - `PlanStart`（开口前的内容）：按钮“和私教聊聊这次结果”→ `POST {purpose: planning}` → `setOpening(true)` 让 `TutorPanel` 的 `autoOpen` 开场；已有空会话时按钮直接 `actions.open()`；直接打字走 `createConversation`，跳过开场。没配模型时显示规则建议链接。
  - 删掉 `lib/placement.ts` 的 `PLAN_HREF`、结果页“去背单词”链接；i18n 中英同步。Vitest 216 通过，tsc、eslint 干净。
- **未完成**：
  - 23.5：E2E `advice.spec.ts`、`planning.spec.ts` 还是旧界面（`planning.spec.ts` 点的是已删掉的链接），要改写；对话页 `?plan=1`（`chat-app.tsx` 的 `planning` prop）现在前端没有入口了，改 E2E 时决定删还是留。
  - 看板和结果页都没在浏览器里实际看过。
- **下一步**：23.5 E2E + README + Docker 重建交用户实测。
- **踩坑**：
  - 之前留下的空规划对话（比如开场被拒）不能 `autoOpen`，否则一打开结果页就调模型，违反 Q23b；所以 `autoOpen` 只在点了按钮之后为 true。
  - 本会话 `pnpm` 是个会递归的 shell 函数，用 `~/.nvm/versions/node/v24.14.0/bin/node node_modules/vitest/vitest.mjs run` 这类绝对路径跑。

---

## 2026-10-01 · 任务 23.3：看板的“今天的学习”对话框

- **做了什么**：
  - 从 `ChatApp` 抽出 `components/chat/tutor-panel.tsx` 的 `TutorPanel`，对话页和看板共用。`ChatApp` 只剩会话列表、`?practice=` / `?plan=` 建会话和 URL 同步。
  - `useChatSession` 新增 `createConversation`、`discardRefused` 两个选项；`MessageList` 新增 `empty` 插槽，改为滚动自身容器。
  - 看板用 `dashboard/today-tutor.tsx` 的 `TodayTutor` 替换 `AdviceCard`：开口前显示规则问候和快捷回复（不调模型），点了才懒建当天的 daily 会话；没配模型时显示规则建议链接。
  - `advice-card.tsx` 改名 `advice-entry.tsx`，删掉轮询和刷新；`lib/advice.ts` 对齐新的 `GET /advice`（`items` + `model_ready`）。
  - i18n、会话列表图标、AI 用量 feature 列表同步。Vitest 208 通过，tsc、eslint 干净。
- **未完成**：
  - 23.4：`components/placement/placement-result.tsx` 的 `NextSteps` 目前只做了最小改动（规则列表 + 跳转 `/chat?plan=1`），要换成 `TutorPanel` 绑定规划对话。`TutorPanel` 的 `empty` 回调已提供 `open()`，但 `open()` 要求会话已存在，所以结果页要先 `POST {purpose: "planning"}` 拿到 id，再 `autoOpen` 或手动开场。
  - 23.5：E2E `advice.spec.ts`、`planning.spec.ts` 还是旧界面，会失败。
  - 没在浏览器里实际看过看板效果（高度 32rem 的卡片是否合适），留到 23.5 / Docker 实测。
- **下一步**：23.4 入学测结果页。
- **踩坑**：
  - 上一会话因为累积的图片和附件太多，请求超过 32MB 被拒，只能新开会话。读前端文件时按需分段读，截图少用。
  - `POST /conversations {purpose: "daily"}` 当天已有会话时会返回那段（200）。原来的“首发被拒就删掉新建会话”逻辑会误删它，所以加了 `discardRefused: false`。
  - 嵌入页面时 `scrollIntoView` 会带着整页滚动，改成设置容器的 `scrollTop`。

---

## 2026-10-01 · 任务 20.6：README 更新到 P1

- **做了什么**（Q20.6a：截图暂缓到网站设计改版后；Q20.6c：词库导入并入快速开始）：
  - `README.md`：状态改 P1；What works now 按学习 / 公示 / 平台重写；快速开始加 `make vocab-import` 和入学测步骤；配置模型改为四个路由的表格；架构图补反思、学习者模型、FSRS；目录和 ADR 列表补全。
  - `README.zh-CN.md`：同步，界面名称用中文文案。
  - 核对：链接、make 目标、路由用途（advice 走 llm 默认路由，不走租户的“对话模型”列表）、功能描述都对照了代码。
- **未完成**：
  - 20.6.1 截图，等网站设计改版。
  - Docker 重建实测：20.5、21、22 的改动都没在 `make up` 下跑过，可以顺带按 README 从零走一遍。要先让用户关掉占内存的程序（见 memory：WSL 构建 OOM）。
  - 本地领先 origin 的提交还没推送。
- **下一步**：问用户是否推送、何时做 Docker 重建实测；之后进入 P2（开工前拆任务）。
- **踩坑**：README 里各任务走哪个路由不能想当然。“今天的建议”用的是 YAML 的 llm 默认路由，租户在设置页改“对话模型”顺序不影响它。

---

## 2026-10-01 · 任务 20.5：11C 剩余三条

- **做了什么**（Q20.5a–c 已确认：静音两条判定都要；空结果按“空 + 重复字符”；测试方式下拉、默认自动）：
  - 20.5.1（8628dcb）：`use-recorder.ts` 用 AnalyserNode 测音量，录音条显示音量；峰值 < -50 dBFS 或有声（> -45 dBFS）时长 < 0.3 秒就不上传，提示检查麦克风。新 E2E `silent-recording.spec.ts`。
  - 20.5.2（27fb0de）：`handlers.heard_speech()`，转写为空 / 无字母数字 / 同一字符占 ≥80% 时附件失败为 `transcription_empty`。不传 VAD。
  - 20.5.3（67593d1）：测试接口 `purpose` 加 `vision`（内置 32x32 PNG，400 → `vision_not_supported`），自动判断看 vision 路由；对话默认模型兜底跳过语音转写模型；卡片改“默认模型” + 说明 + “测试方式”下拉。ADR 0008 追加一段。
  - 验证：后端 829、Vitest 206、E2E 36 全过，ruff / mypy / eslint / tsc 干净。
- **未完成**：20.6（README）；Docker 全栈仍是旧镜像，任务 20.5、21、22 都没在 `make up` 下实测。
- **下一步**：20.6 开工前在 PROGRESS 拆任务并和用户确认（截图按 Q20b：英文界面、Playwright + 假模型、放 `docs/images/`）。
- **踩坑**：
  - Playwright 的 `test.use({ launchOptions })` 不能放在 describe 里（会强制新 worker），要放到单独的 spec 文件顶层。
  - `--use-file-for-fake-audio-capture=<wav>` 可以让 Chromium 假麦克风播放指定文件，拿静音 WAV 测静音拦截。
  - AudioContext 没进入 running 时 AnalyserNode 读到的全是 0；这种情况必须当成“测不到”而不是“静音”，否则会拦掉所有录音。
  - 设置页 E2E 的用量计数会随连接测试次数变化（每次测试都记用量）。

---

## 2026-09-30 · 任务 21.4–21.5：对话卡片前端与 E2E（任务 21 全部完成）

- **做了什么**：
  - 21.4（83bf64c）：
    - `lib/cards.ts`、SSE `card` 事件、`use-cards.ts`、`tutor-cards.tsx`。卡片挂在那一轮回复下，提议卡可以确认、拒绝、撤销，409 有文案说明。
    - `turn-activity` 显示工具调用、降级和规划依据；会话列表给规划对话加图标。
    - 修了任务 22 遗留的 `e2e/advice.spec.ts`。
  - 21.5：
    - 新增 `e2e/planning.spec.ts`，覆盖全流程。
    - 假模型能流式返回工具调用。
    - `answerOne` 挪到 `e2e/helpers.ts`。
    - 修复“返回”时重复建会话的问题（见下方踩坑）。
  - 验证：E2E 35 个全部通过，Vitest 198，eslint / tsc 干净，后端 812。
- **未完成**：
  - 20.5（11C 剩余三条）、20.6（README）。
  - Docker 全栈仍是旧镜像：任务 21、22 都没在 `make up` 下实测过。有两个新迁移，后端启动时会自动迁移。
- **下一步**：
  - 20.5 开工前先在 PROGRESS 拆任务，和用户确认。
  - 用户想实测任务 21 时，要先停掉占内存的程序再 `make up`（见 memory：WSL 构建 OOM）。
- **踩坑**：
  - 用 `window.history.replaceState` 把 `/chat?plan=1` 改成 `/chat?c=<id>` 后，离开再按“返回”，Next 会用该条目缓存的旧 searchParams（`plan=1`）渲染页面。`ChatApp` 挂载时要以 `window.location` 的 `?c=` 为准，不然会再建一个会话。
  - 练习会话之前一直有同样的问题，只是因为会复用未开始的会话，所以没暴露出来。
  - 假模型要流式返回工具调用：delta 里放 `tool_calls: [{index, id, type, function: {name, arguments}}]`；`id` 每次要唯一，因为 `tutor_cards` 对 (会话, tool_call_id) 有唯一约束。

---

## 2026-09-30 · 任务 21.1–21.3：私教工具调用与确认卡（后端）、入学测后的规划对话

- **做了什么**：
  - 21.1 ADR 0015 已采纳（§8 五条按推荐）。
  - 21.2 后端（a6df551）：
    - 新表 `tutor_cards`；`app/cards/`：`tools.py` 参数模型与校验，`service.py` 写卡 / 确认 / 拒绝 / 撤销，`runtime.py` 按轮绑定身份。
    - `chat_graph` 改为 `tutor ⇄ tools`（2 次往返 × 3 个调用、15 秒超时，厂商拒绝时去掉工具重答）；SSE `card` 事件。
    - `api/cards.py`：`GET /conversations/{id}/cards`、`POST /cards/{id}/apply|decline|undo`；`chat_tools` 用量 task。
  - 21.3（a2940a3）：
    - `conversations.purpose='planning'`；`chat/planning.py` 每轮注入入学测结果、答错语法点和建议候选，并据此限定卡片范围；开场 `plan_opening`，登记为 `plan_start`。
    - 入学测后建议立即重生成。
    - 前端结果页“接下来做什么”+“和私教聊聊怎么学”（`/chat?plan=1`）。
  - 两个迁移都已 `make migrate` 到开发库（只新增）。
  - 验证：后端 812 通过，Vitest 190，ruff / `mypy app` / eslint / tsc 干净。
- **未完成**：21.4（前端卡片），21.5（E2E + 交接），20.5、20.6。
- **下一步 21.4**：
  - 聊天页收到 SSE `card` 事件时，在当前私教气泡下渲染卡片；打开会话时用 `GET /conversations/{id}/cards` 按 `turn_id` 挂到对应回复下。消息 id 就是 turn 的学习者消息 id，和活动的挂法相同，见 `use-activity`。
  - 卡片种类：
    - `word_book` / `learning_goal`：确认 / 拒绝 / 撤销（409 `setting_changed` 要提示）；
    - `practice`：用 `practiceHref`；
    - `link`：`kind` → 路径 `vocab_review:/vocab/review`、`vocab_screen:/vocab/screen`、`placement:/placement`、`learner:/learner`、`word_books:/vocab`，并显示 `live` 数字。
  - `turn-activity` 要显示 4 个 tool 步骤（`card_kind`）和 `tools: skipped`；`load_context` 的 `planning`。
  - 会话列表给规划对话加标识。
  - 中英文案，Vitest。
- **踩坑**：
  - 同一轮的并行工具调用会同时执行 put_card 的“先查后写”去重，出现重复卡片。已用 `DatabaseTutorTools` 里的 `asyncio.Lock` 让写卡串行。这个问题只在全量测试里偶发。
  - 从别的测试模块导入 pytest fixture 时，参数上要加 `# noqa: F811`（仓库惯例）。
  - `node` 在 Bash 里被 shell 函数劫持（`_load_nvm` 无限递归），要用 `$HOME/.nvm/versions/node/v24.14.0/bin/node` 的绝对路径。
  - 放入学测页的组件如果挂了 `AiBadge` 或建议，Vitest 里要 mock `@/lib/ai-usage` 的 `loadEstimates` 和 `@/lib/advice` 的 `fetchAdvice`。否则它们会占用按顺序排好的 `api` mock。
  - 自动生成迁移不认 CHECK 约束，要手写 `op.create_check_constraint`。自动生成对着 `lingo_test` 跑（`DATABASE_URL=...lingo_test`），不碰开发库。

---

## 2026-09-30 · 任务 22：AI 用量标记（22.1–22.4 全部完成）

- **做了什么**：
  - 22.1 后端：`backend/app/usage/features.yaml` 列出 7 个功能（`chat_message`、`chat_image`、`chat_pdf`、`chat_audio`、`practice_start`、`advice`、`memory_edit`）各自触发的调用和默认估计，由 `features.py` 校验。`estimates.py` 按 task 取租户最近 20 次成功调用求平均，并用 `resolve_route` 给出当前模型。接口 `GET /usage/estimates` 登录即可访问。
  - 22.2 前端：`components/ai-badge.tsx` + `lib/ai-usage.ts`，shadcn `ui/popover.tsx`（Base UI，`openOnHover`）。
  - 22.3 挂载：聊天发送 / 附件（一个标说明两个功能）/ 录音按钮角上；三处“开始练习”；建议卡片标题和 AI 条目（替换了原来的纯文字 AI 标）；记忆列表标题。
  - 22.4：ADR 0014、CLAUDE.md 约束、`docs/agent-tools.md`“AI 用量标记”对照表、PLAN、P1 计划 §7.6。E2E `e2e/usage.spec.ts` 通过。
  - 验证：后端全量 790 通过；Vitest 189 通过；ruff、`mypy app`、eslint、tsc 都干净。提交：7855108、be4f1cb、5d423cf 和本条。
- **未完成**：没有。任务 21 还没动。
- **下一步**：21.1（ADR 0015 私教工具调用与确认卡）。现状见上一条交接的“开工前需要的现状”。任务 21 的新工具（如换词书、设目标）如果会调用模型，要按 ADR 0014 登记到 `features.yaml` 并挂标。规划对话本身走 `chat`；如果新增 task（如 `plan_opening`），也要登记。
- **踩坑**：
  - Python 3.12 下 `except A, B:` 是语法错误，要写成 `except (A, B):`。
  - next-intl 的 key 有类型约束，`` t(`task.${string}`) `` 过不了 tsc，要先用类型守卫（`isAiTask`）收窄。
  - 向量化不走 chat 回调，不写 `llm_usage`，所以 `memory` 估计始终是默认值（清单里是 `history: false`）。
  - `mypy app tests` 里有 14 个历史遗留的测试文件类型错误；`make lint` 只检查 `mypy app`，和本任务无关。
  - Playwright 无头 Chromium 缺中文字体，截图里的中文会显示成方框，不是页面问题。
  - Docker 全栈仍是旧镜像（没有本任务的改动）；要实测需要重新 `make up`，放到 20.5 / 20.6 一起做。

## 2026-09-30 · 任务 20.2–20.4：Docker 重建、用户实测，反馈拆成任务 21、22

- **做了什么**：
  - 20.2：`make up` 重建全栈。迁移到 head `c6350c4e826a`，`/healthz` 200，前端和 `/api` 代理正常。空闲内存：backend 约 193MiB、frontend 约 83MiB、postgres 约 110MiB。
  - 按用户要求清空开发库：TRUNCATE 除 `words`（ECDICT 38,243 条）、`alembic_version`、`checkpoint_migrations` 以外的所有表。
  - 20.4：用户按 `docs/plans/P1-demo-checklist.md` 实测完成，除 AI 交互外没有问题。反馈两条：
    - 入学测后要有学习建议，能直接进 AI 对话引导，私教能代为设置词书、语法练习、学习目标等 → **任务 21**
    - 所有消耗 token 的功能点要带“AI”标记，悬停显示用量预估和说明（用户视为开源卖点）→ **任务 22**
  - 两个任务的 Q 已确认（见看板 Q21a–d、Q22a–c），子任务已写进 `docs/PROGRESS.md`，提交 d16abd4。
- **未完成**：任务 22、21 都没动代码。子任务拆分已经给用户看过，**用户还没回“开始”**。新会话先请用户确认拆分，再从 22.1 开工。
- **下一步**：22.1 → 22.4 → 21.1 → 21.5 → 20.5 → 20.6。开工前需要的现状（已查过）：
  - `llm_usage` 每条记录有 `task`（`chat`、`vision`、`reflect`、`advice`、`memory`、`practice_opening`）、`input_tokens`、`output_tokens`、`audio_seconds`，没有价格（ADR 0005）。
  - 模型调用点：
    - `chat_graph.py` 的 `tutor`（`chat` / `vision`）
    - `memory/reflection.py`（`reflect`：反思 + 会话摘要）
    - `memory/embedding.py`（`memory`）
    - `attachments/reading.py`（`vision`）
    - `attachments/handlers.py`（ASR）
    - `advice/writer.py`（`advice`）
    - 开场通过 metadata `usage_task=practice_opening` 记账
  - 私教目前**没有任何工具调用**（没有 `bind_tools` / `ToolNode`），图是 `load_context → tutor`。
  - `PUT /vocab/book` → `progress.choose_book()` 没有撤销；换书会把 `screen_offset` 清零，撤销要保存旧值。
  - `UserProfile` 已有 `goal`、`target_exam`、`daily_minutes`、`manual_fields`，设学习目标不需要迁移。
  - 建议缓存在 `advice/service.py`：`MIN_INTERVAL` 10 分钟、`BY_HAND_EVERY` 1 小时。入学测完成要绕过 10 分钟间隔，入口在 `placement/writeback.py` 的 `save_result` 之后。
  - 结果页组件是 `frontend/src/components/placement/placement-result.tsx`。
  - ADR 编号：0014 = AI 用量公示，0015 = 私教工具调用与确认卡。
- **踩坑**：
  - 第一次 `make up` 时，corepack 下载 pnpm 报 `DEPTH_ZERO_SELF_SIGNED_CERT`。构建走 Clash 代理 127.0.0.1:7890，事后在宿主机和容器里复查证书都正常，重跑成功，判断是代理临时问题。
  - 后端健康检查是 `/healthz`，不是 `/health`。
  - compose 里 postgres 的用户名不是 `postgres`，要用 `sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'`。
  - zsh 下 `grep --include=*.py` 要加引号，否则报 no matches found。
  - Docker 全栈仍在运行（含 asr）。
- **开发库要保留**：用户在开发库 `lingo` 里有一个测试账号，包括 2 个模型连接、3 条路由、1 次完成的入学测（产生 20 条语法证据）和 1 个会话。还没有词书、卡片和记忆；`llm_usage` 只有 `advice` 和 `asr` 两类记录。用户要用这个账号一直测到功能做完，最后再换新账号完整测一轮。所以：
  - 迁移只能做增量，不能要求清库。
  - 不要清库、不要删 `pgdata` 卷、不要改 `.env` 里的 `CREDENTIALS_ENCRYPTION_KEYS`。改了它，已存的 key 就解不开了。
  - 测试用的是单独的 `lingo_test` / `lingo_e2e` 库，不影响开发库。

---


## 2026-09-30 · P1e 任务 19：针对语法点的练习对话

- **做了什么**：用户确认 Q19a–Q19d 均按推荐（私教自动开场；练习里的对错与普通对话同权；学习者没开口就复用；入口加 `/learner` 详情和看板常错语法点）；Q19e 没单独问，按默认（不自动结束，约 5 句用对后小结）。
  - 19.1 迁移 `c6350c4e826a`（`conversations.focus_kc_id`）；`POST /conversations {focus_kc_id, locale}`、复用规则 `chat/service.py` `unstarted_practice`；`ConversationOut.focus_kc`。
  - 19.2 `app/chat/practice.py` + `prompts/practice.md`：`load_context` 每轮拼练习指引（档位不给数字），UntrackedValue 不进 checkpoint；`ContextRead.practice_kc`。
  - 19.3 `POST /conversations/{id}/opening`（`api/chat.py` `start_opening` / `open_practice`，与发消息共用 `_reply`）；`tutor` 在没有学习者消息时临时加 `prompts/practice_opening.md`；`usage/recorder.py` 支持 metadata `usage_task`，开场记为 `practice_opening`，不计入打卡。
  - 19.4 前端：`streamOpening`、`useChatSession.open` / `readyFor`、`ChatApp` 的 `?practice=` 与自动开场、`PracticeBar`、列表标记、三个入口。
  - 19.5 `e2e/practice.spec.ts`；活动公示补上 `practice_kc`；`docs/agent-tools.md`、P1 计划 §7.5.3。

  提交 aa7c71d、09042ce、71cd6a1、66637a3 和本次。后端 777、Vitest 180、Playwright 33 全部通过，ruff、mypy、tsc、eslint 干净。
- **未完成**：
  - 练习指引和开场提示只用假模型验证过“指引送到了模型”，真实模型下练习对话的质量（讲解是否简短、是否真的引导造句、约 5 句后是否小结）还没看过。
  - 仍然没有在 Docker 全栈上看过任务 16–19，要 `make up` 重建。
- **下一步**：任务 20（P1 Demo 全流程实测 + README 更新）。需要用户实测：建议在 Docker 全栈、真实模型下走一遍 注册 → 配模型 → 入学测 → 选词书背词 → 聊天 → 看板建议 → 语法练习。开工前拆子任务、和用户确认。
- **踩坑**：
  - 同一个 thread 第二次 `aupdate_state` 要给 `as_node`，否则 `InvalidUpdateError: Ambiguous update`。
  - ruff `RUF001` 会拦中文全角标点（`：`、`（）`）：确实需要时加单行 `# noqa: RUF001`。
  - React Compiler 的 `react-hooks/set-state-in-effect` 是否报错取决于整个 hook 能否被分析：把事件处理改成 `useCallback` 后，`use-chat-session` 里原本不报的 `setMessages([])` 开始报。“当前会话的历史已加载”要用加载完成时记下的 id 在渲染时比较得出，不能在 effect 里同步 set。
  - 开场没有学习者消息，活动的 turn id 固定为 `opening`；前端从历史恢复时，第一条是私教消息就挂到 `opening`。
  - Playwright 里消息的 `data-role` 在 `<li>` 上，不在 `[data-slot="message"]` 上。

---

## 2026-09-30 · P1e 任务 18：看板学习建议（候选 → 模型挑选 → 缓存）

- **做了什么**：用户确认 Q18a–Q18e 均按推荐。
  - 18.1 `app/advice/candidates.py`；`rules.yaml` 加 `advice:`，版本升到 `2026-09-30.3`。
  - 18.2 `app/advice/writer.py`、`prompts/advice.md`。
  - 18.3 `app/advice/service.py`（`read`、`needs_refresh`、`AdviceRefresher`）；表 `learning_advice`，迁移 `a7d45c7043a3`；接入 `main.py` 生命周期。
  - 18.4 `app/api/advice.py`：`GET /advice`、`POST /advice/refresh`。
  - 18.5 `lib/advice.ts`、`components/dashboard/advice-card.tsx`；`PlacementOut.retest_due` + 聊天页引导条的 `retest`。
  - 18.6 `e2e/advice.spec.ts`，`fake_llm.py` 能回答 `AdviceDraft`；更新 `docs/agent-tools.md` 和 P1 计划 §7.5.2。

  提交 9107c97、d6c788f、d642465、16ec7d4、970310a 和本次。后端 759、Vitest 173、Playwright 32 全部通过，ruff、mypy、tsc、eslint 干净。
- **未完成**：
  - 仍然没有在 Docker 全栈和真实模型上看过建议的实际文字质量（提示词只用假模型验证过结构）。
  - 任务 16–18 都要 `make up` 重建后才能看到。
- **下一步**：任务 19。
  - `conversations.focus_kc_id` + `load_context` 里加练习指引。
  - `adviceHref` 里的 `grammar_practice` 改为新建练习对话（现在是 `/learner?kc=`）。
  - 开工前拆子任务、和用户确认。
- **踩坑**：
  - JSONB 列写 Python `None` 存的是 JSON `null`，不是 SQL NULL：`placement_sessions` 的 `done_result` 约束会拒绝，测试里不要给未完成的测试传 `result=None`。
  - SQLAlchemy 2.1 的 `Result.tuples()` 已废弃，直接 `.all()`。
  - eslint 的 `react-hooks/purity` 不允许在渲染时调用 `Date.now()`：冷却分钟数要在拿到响应时算好，存进 state。
  - 前端没有 prettier，格式靠手写和 eslint。
  - 重测提醒如果只按种类记住“已关闭”，下一次到期也不会再提醒。所以按 `retest:<finished_at>` 记。
  - 手动刷新以外，候选变化触发的重新生成有 10 分钟最短间隔。E2E 里要看到 AI 建议，得点“刷新建议”。

---

## 2026-09-30 · P1e 任务 17：能力看板（`GET /dashboard` + `/dashboard`）

- **做了什么**：用户确认 Q17a–Q17d 均按推荐：
  - a：词书“已掌握”= 复习状态且稳定度 ≥ 21 天。
  - b：对话轮数按 `llm_usage` 统计。
  - c：复习或对话都算学习；今天没学时从昨天往前数。
  - d：技能换算到同一 CEFR 刻度。

  各子任务：
  - 17.1 `app/dashboard/service.py`、`app/api/dashboard.py`、`app/adaptive/cefr_scale.py`；`flow.known_in_basis`；`rules.yaml` 升到 `2026-09-30.2`；迁移 `1ec9ad47e438`（`llm_usage (user_id, created_at)` 索引）。
  - 17.2 shadcn chart + recharts 3.8.0，`--chart-*` / `--heat-*` 配色（经 dataviz 校验脚本验证）。
  - 17.3–17.5 `components/dashboard/*`、`lib/dashboard.ts`、首页和导航、proxy。
  - 17.6 `e2e/dashboard.spec.ts` 和文档。

  提交 bacefcf、f2c5a53、53677a1 和本次。后端 718、Vitest 166、Playwright 31 全部通过，ruff、mypy、tsc、eslint 干净。
- **未完成**：无。仍然没有在 Docker 全栈和真实词库上手动走一遍（任务 16、17 都要 `make up` 重建后才能看到）。
- **下一步**：任务 18（学习建议），开工前拆子任务、和用户确认。建议卡片放在看板上；候选里的 `placement` 要包括“超过 60 天重测”。
- **踩坑**：
  - 能力值在 A1 最底部时，刻度位置是 0，条形宽度为 0 就不画了。现在最短留 0.08。
  - Recharts 3 的 `Legend` 默认 `itemSorter="value"`，会按名称排序，要传 `itemSorter={null}`。
  - WSL 里的无头 Chromium 没有中文字体，截图里的中文是方块，不是页面的问题。
  - 看板的滚动在内层 div 上，`fullPage` 截图截不到下面；要先把视口调高。
  - E2E 的小词库下，入学测结果是“约 7 词 / 参考 C2”，这是测试数据造成的（入学测结果页也是这样），真实词库不会。
  - 任务 16 漏了 `/placement` 的 proxy 保护，这次已补上。

---

## 2026-09-30 · P1d 任务 16：/placement 页面 + 聊天页引导条

- **做了什么**：用户确认 Q16a–Q16d 均按推荐：
  - a：没测完就显示引导条，关闭状态存 localStorage。
  - b：由后端给 `/learner` 带上词汇量。
  - c：结果页可以重新测试，要二次确认。
  - d：批量标熟放在结果页和筛选页。

  各子任务：
  - 16.1 `GET /learner` 技能行加 `cefr` / `vocab_size` / `reliable`，`writeback.latest_result` 与批量标熟共用。
  - 16.2 `lib/placement.ts` 和 5 个错误码文案。
  - 16.3 `components/placement/placement-app.tsx`（说明 / 作答 / 断点续做，Y/N、1–4 快捷键）。
  - 16.4 `placement-result.tsx` 和 `components/vocab/placement-known.tsx`。
  - 16.5 `components/chat/placement-banner.tsx`、导航入口、筛选页标熟卡片。
  - 16.6 `/learner` 技能显示词汇量和等级，入学测证据标明来源。
  - 16.7 `e2e/placement.spec.ts` 和文档。

  提交 c53a513、f0e2779、812d2ff、9ba72f3、69bb7df、16547ed 和本次。后端 696、前端 Vitest 158、Playwright 30 全部通过，ruff、mypy、tsc、eslint 干净。
- **未完成**：无。没有在 Docker 全栈和真实词库上手动走一遍，运行中的 Docker 服务还是旧代码，需要 `make up` 重建。
- **下一步**：任务 17（`GET /dashboard` 聚合接口 + `/dashboard` 页面，登录后首页改为看板），开工前拆子任务、和用户确认。任务 18 的学习建议要包括“超过 60 天重测”的提醒（引导条只管没测完的情况）。
- **踩坑**：
  - 在 Bash 工具里用 `export PATH=… && pnpm …` 仍会挂起。要写成 `B=~/.nvm/versions/node/v24.14.0/bin; export PATH=$B:$PATH; $B/pnpm …`，见记忆 env-node-nvm-hang。
  - 子组件的 effect 先于父组件执行。筛选页挂了 `PlacementKnown` 之后，它的请求会插到 `ScreenApp` 按顺序 mock 的请求中间，所以 `screen-app.test` 里把它 mock 掉了。
  - 结果页挂载后会再请求一次 `/vocab/placement-known`。作答流程测试最后一步的断点要用 `toHaveBeenCalledWith`，不能用 `toHaveBeenLastCalledWith`。
  - 入学测的错题证据没有原句和改正，`error_type=wrong_choice` / `severity=medium` 只是写回时的占位值。`/learner` 对 `source=placement` 的证据不显示这两项。
  - E2E 里“入学测”“对话”这两个链接名会和“开始入学测”“去和私教对话”互相匹配，必须加 `exact: true`。

---

## 2026-09-30 · P1d 任务 15：placement 子图 + 接口 + 结果写回 + 批量标熟

- **做了什么**：用户确认 Q15a–Q15d 均按推荐（真词精确过滤、词汇量按词计数；语法测试中性起点；学习者确认后批量标熟、可撤销；总体等级 = 语法等级）。15.1 迁移 `347f8448994f`（`placement_sessions`、`placement_item_stats`、`user_cards.source` 加 `placement`）；15.2 `placement/words.py`；15.3 `placement/flow.py`（纯函数）+ `agents/placement_graph.py`；15.4 `placement/writeback.py`；15.5 `app/placement/service.py` + `app/api/placement.py`；15.6 `services/vocab/placement_known.py` + `/vocab/placement-known`；15.7 文档。`rules.yaml` 升到 `2026-09-30.1`。提交 b03d454、cdf1989、86e3bdb、428d1b5、b799a11 和本次。后端全量 695 通过，ruff、mypy 干净。
- **未完成**：无。前端没有改动。
- **下一步**：任务 16（`/placement` 页面 + 聊天页引导条），开工前拆子任务、和用户确认。已知要一起处理的界面问题：
  - `/learner` 的技能列表直接显示 `rating`，vocab 存的是 ln V（约 8），要改成显示估计词汇量；`GET /learner` 可能需要带上最近一次入学测的词汇结果。
  - `/learner` 证据列表对 `source=placement` 没有来源标签（`components/learner/kc-item.tsx` 只处理了 chat），要加“入学测”。
  - 新错误码的中英文文案：`words_not_imported`、`stale_question`（前端收到后重新 `GET /placement/{id}`）、`invalid_answer`、`placement_not_in_progress`、`placement_not_found`。
  - 结果页和筛选页接 `GET/POST/DELETE /vocab/placement-known`；`unavailable` 有 `no_placement` / `unreliable` / `no_book` 三种。
  - 引导条用 `GET /placement/latest`（返回 null 表示从没测过）。
- **踩坑**：
  - ECDICT 的 `exchange` 里有 `0:` 不代表是屈折形式：number 被记成 numb 的比较级、better 记成 good 的比较级。要看这个词自己有没有其他变形（`words.is_testable`）。
  - 函数名以 `test` 开头（`testable`）会被 pytest 当成测试收集，已改名为 `is_testable`。
  - 同一场测试的串行化用 `pg_advisory_xact_lock`，不能用 `SELECT … FOR UPDATE`：图的 `finish` 会在另一个连接里给同一行加 `FOR UPDATE`，请求所在的事务还没结束，两边会互相等待。
  - `start` 要持锁跑到出第一题再提交；先提交的话，并发的第二个请求会读到已经存在、但还没有题目的测试。
  - Alembic autogenerate 检测不到 CHECK 约束的变更，`user_cards.source` 是手写迁移。
  - 测试库的 `words` 是空的，所以词池不做进程级缓存（`DatabaseWords` 空池不缓存），由 context 注入；`placement_item_stats` 没有外键，已加进 `tests/conftest.py` 的清理列表。

---

## 2026-09-30 · P1d 任务 14：语法题库 + 假词 + 词汇量估计 + 语法选题定级

- **做了什么**：用户确认 3 点：题库授权按教师标准自审；第二部分只考语法；假词离线生成静态清单。新增 `app/adaptive/placement/`：`items.py` + `items.yaml`（90 题，难度由四个维度分现算，启动时校验）、`pseudowords.py` + `pseudowords.txt`（4 元组模型，对照完整 ECDICT 过滤，300 个）、`vocab_size.py`（对数逻辑模型 + 误报率写进似然 + 最大后验拟合 + 就近频段选题）、`grammar_test.py`（最大后验拟合能力 + 标准误、选题、结束判定、CEFR 分界）。`rules.yaml` 加 `placement.vocab` / `placement.grammar`，版本号升到 `2026-09-29.5`。ADR 0010 / 0012、P1 计划 §6.1、PLAN 第二·五节加落地记录。提交 39e40f4、c958afb、c69da84 和本次。pytest 全量 647 通过（单测 407），ruff、mypy 干净。
- **未完成**：无。
- **下一步**：任务 15（placement 子图：`pick_item → ask（interrupt）→ update_estimate → 结束判定`；`POST /placement`、`/placement/{id}/answer`、`GET /placement/{id}/result`；`placement_sessions` 表、题目统计表（测后用最终能力回算难度，ADR 0012 §3）；结果写 `user_profile.cefr_level`、`skill_estimates`、BKT 先验、`kc_evidence(source=placement)`）。需要决定的点：真词从 `words` 表按 `frq` 取时排除屈折形式（`exchange` 含 `0:`）和专有名词；语法测试的先验均值是否用画像里已有的 CEFR；词汇量结果怎样建议熟词筛选的起点。开工前拆子任务、和用户确认。
- **踩坑**：
  - 起草语法题时最常见的问题是“干扰项在某种语境下也对”（美式英语过去式代替现在完成时、`There's a lot of students`、`while I had a bath`、英式 `recommended that he stops`）。审核标准写在 `items.yaml` 文件头，扩充题库时照着查。
  - 四选一题有 0.25 的猜测下限，20 题的标准误降不到 0.55 以下，“不确定度足够小就提前结束”实际不会触发；要缩短测试只能加题型（非选择题）或放宽标准误。
  - 三元组模型生成的假词不像英语（`chm`、`chf` 开头），改成 4 元组才像样。假词清单不要手改：`tests/unit/test_pseudowords.py` 在本机有 `data/ecdict.csv` 时会重新生成并比对。
  - `float ** float` 在 mypy 里是 `Any`，用 `math.pow`。

---

## 2026-09-29 · P1c 任务 13：自动收词 + 聊天里选词加入生词本

- **做了什么**：用户确认 4 点：已有卡片的词自动收词不改动（只记“已在学”）；回复明细里直接放“移出”；只能从私教回复里选单个词；不记出处句子。后端：`Reflection.vocab_candidates`（消息短 id + 原形）+ `prompts/reflect.md` 新一节；`reflection.asked_words` 校验；`mine.collect`（只为没有卡片的词建 `auto` 卡）、`mine.on_list`；worker `_collect_words`（打标之后执行，失败记 `failed`）；活动 `vocab_collect`；活动接口加 `words_on_list`。前端：`use-activity` 的 `wordsOnList` / `removeWord`，`turn-activity` 的收词明细，`select-to-add.tsx`（选词浮出按钮）。E2E 假模型认 `what does "X" mean`。提交 5640a33、b110fdf、14d50ac 和本次。pytest 567、Vitest 142、Playwright 29。
- **未完成**：无。
- **下一步**：任务 14（P1d 入学测：语法题库 LLM 起草 → 用户审核、假词生成、词汇量估计），开工前拆子任务、和用户确认。
- **踩坑**：
  - 项目里的 `sonner.tsx` 没有挂 `<Toaster>`，要用轻提示得自己挂；这次选词用就地浮层代替。
  - jsdom 没有 `Range.getBoundingClientRect`，单测里要自己补（`select-to-add.test.tsx` 的 `beforeEach`）。
  - 选中结果提示时清空选区会触发 `selectionchange` → 按钮消失，所以提示要自己记位置，不能跟着选区走。
  - Bash 工具里 `pnpm` 是 zsh 函数（nvm 懒加载），会无限递归；用 `$HOME/.nvm/versions/node/v24.14.0/bin/pnpm` 并把该目录放进 PATH。
  - 集成测试里 `learner()` 取到的 `user` 在 `expire_all()` 之后再读 `.id` 会触发 MissingGreenlet，先存 `user_id`。

---

## 2026-09-29 · P1c 任务 12：背词接口和四个页面

- **做了什么**：用户确认生词本删除一律真删、加词按 精确 → 忽略大小写 → `exchange` 还原原形、P1 不做撤销评分。后端 `app/api/vocab.py`（10 个接口）+ 服务层 `progress.py`、`mine.py`，`queue.py` 加 `today_counts`；前端 `lib/vocab.ts`、`components/vocab/`（`vocab-app`、`screen-app`、`review-app` + `use-review-session`、`mine-app`）、四个页面、导航、proxy 保护、中英文案；E2E 库导入 fixture 词库，`e2e/vocab.spec.ts` 2 个用例。提交 06fec04、2af7a0d、aca5ff6、e368378、d99842d 和本次。pytest 560、Vitest 135、Playwright 27。
- **未完成**：无。
- **下一步**：任务 13：reflect 的 `vocab_candidates` → 生词本（`mine.add(..., source="auto")` 已可直接用）+ 聊天回复里选中文字加入生词本；按 ADR 0013 同步 `docs/agent-tools.md` 并在活动里公示。开工前拆子任务、和用户确认。
- **踩坑**：
  - ECDICT 子集里没有 went、ran 这种纯变形词条（导入时过滤了），还原原形要反查原形词条的 `exchange`（正则匹配除 `0:`、`1:` 以外的变形）。
  - eslint 的 `react-hooks/set-state-in-effect`：effect 里调用的 async 函数哪怕 setState 在 await 之后也会被报；改成 `promise.then(set…, …)` 的写法就不报（和 learner-app 一致）。
  - Playwright 里 `getByRole("alert")` 会同时命中 Next 的路由播报器（`__next-route-announcer__`），要加 `filter({ hasText: /\S/ })`。
  - 无头 Chromium 没有中文字体，截图里中文是方块，不是页面问题。
  - 别在 `frontend/` 下用 `git checkout -- .` 清理测试产物：会连未提交的改动一起丢掉（这次丢了 `run_backend.py` 的改动，已重做）。

---

## 2026-09-29 · P1c 任务 11：词书、卡片、FSRS 调度、每日队列、熟词筛选

- **做了什么**：用户确认词书写在代码里（9 本，含牛津 3000）、一次一本、单词掌握度不写 `kc_mastery`。`fsrs` 6.3.2；迁移 `92cbcc17eefe`（`user_cards`、`review_logs`、`user_word_book`）；`rules.yaml` 的 `vocab` 一节（版本 `2026-09-29.3`）；`app/services/vocab/` 下 `books.py`、`scheduler.py`（`review`、`retrievability`、`learner_zone`、`day_bounds`）、`queue.py`（`daily_queue`）、`screening.py`（`next_batch`、`submit`）。只有服务层，还没有接口和页面。提交 25be313、df51caa、686a874 和本次。测试新增 22 个，pytest 557。
- **未完成**：无。
- **下一步**：任务 12：背词接口（选书、队列、评分、筛选、生词本增删）+ `/vocab`、`/vocab/screen`、`/vocab/review`、`/vocab/mine` 页面。开工前拆子任务、和用户确认。浏览器时区要由前端传给队列接口（画像里没有时区时用）。
- **踩坑**：
  - FSRS 6 没有 New 状态：新卡就是 `State.Learning` 且 stability 为空。“新词”用 `user_cards.status` 表示，没复习过的卡 FSRS 列全为空。
  - `fsrs.Card.to_dict()` 返回 TypedDict，不能直接 `pop("card_id")`（mypy 报错），先转成普通 dict。
  - 熟词筛选如果只在“认识比例高”时前移起点，没勾的词会被反复展示；改为每批都前移。
  - 测试日界时注意方向：上海比 UTC 快 8 小时，“上海是今天、UTC 还是昨天”的时刻是 UTC 前一天 16:00 之后。
  - `select … FOR UPDATE` 要加 `populate_existing`，否则同一 session 里已加载的对象不会刷新成锁定后的值。

---

## 2026-09-29 · P1c 任务 10：`words` 表 + ECDICT 导入

- **做了什么**：用户确认下载固定到 ECDICT 提交 `bc015ed` 并校验 sha256、在宿主机用 uv 跑。`Word` 模型 + 迁移 `b50a63a12ed3`；`app/services/vocab/import_ecdict.py`（流式过滤 → COPY 临时表 → upsert）；`make vocab-import`；`Settings.ecdict_url` / `.env.example`；README 中英、ADR 0011、P1 计划。开发库已导入 38,243 条。测试：单测 3、集成 2，pytest 535。
- **未完成**：无。容器里的导入做法（`docker compose cp` + `--csv`）写进了 README，但没实测。
- **下一步**：任务 11：词书（按 tag 的虚拟分组）、`user_cards`、`review_logs` + py-fsrs 调度 + 每日队列。开工前拆子任务、和用户确认；要 `uv add fsrs`（不带 optimizer）。
- **踩坑**：
  - 临时表用 `LIKE words INCLUDING DEFAULTS` 会带上 id 的序列默认值，每次导入白白消耗 3.8 万个 id；改用 `CREATE TEMP TABLE … AS SELECT <列> FROM words WITH NO DATA`。
  - ruff 的 ASYNC240 不允许在 async 函数里调用 pathlib 的阻塞方法：下载用 `anyio.Path`，校验缓存放进 `asyncio.to_thread`；测试里的 glob 也要用 `anyio.Path`。
  - 运行时的 HTTP 库是 `httpx2`（`httpx` 只是 dev 依赖）。
  - ECDICT 的 `pos` 列全为空；`went`、`ran` 这类屈折形式大多没有排名，不在子集里，`held` 有排名所以在。

---

## 2026-09-29 · P1b 任务 9：学习者模型接口 + `/learner` 页面

- **做了什么**：拆成 9.1–9.4，用户确认三点：“删除所有学习记录”连同 `grammar_tagging` 活动一起删；支持删单条证据并同步改活动摘要；列表只显示接触过的 KC。后端 `app/adaptive/learner.py` + `app/api/learner.py`（`GET /learner`、`GET /learner/kcs/{kc_id}/evidence`、`DELETE /learner/evidence/{id}`、`DELETE /learner`），`activity.untag` / `forget_grammar_tags`；`rules.yaml` 加 `bkt.weak`（版本 `2026-09-29.2`）。前端 `/learner`（筛选、掌握度条 + 文字、懒加载证据、删单条 / 全部、`?kc=` 直达），导航和 `proxy.ts`，聊天活动里的语法点链到 `/learner?kc=`。测试：集成 3、Vitest 5、E2E 1。提交 ab9d0ae、aafe471 和本次文档提交，未推送。
- **未完成**：无。
- **下一步**：P1c 任务 10：`words` 表 + ECDICT 导入脚本 + `make vocab-import`。开工前拆子任务、和用户确认。
- **踩坑**：
  - `session.scalars()` 的结果没取完就执行下一条查询，会报 `'ChunkedIteratorResult' object is not subscriptable`（看起来像 `dict()` 出错），先 `.all()`。另外 SQLAlchemy 2.1 里 `Result.tuples()` 已弃用。
  - 证据“是否计入 BKT”要对该 KC 的完整历史跑 `bkt.counted`（每轮上限看同一轮的其他证据），不能只看当前页。`Observation` 是可比较的 frozen dataclass，内容相同的两条会相等，所以用 `id()` 判断是否被保留。
  - E2E 里按 `hasText: "She like"` 筛证据会连会话标题“She like music.”一起匹配，要用 `has: getByText(..., { exact: true })`。
  - 改了 `rules.yaml` 版本号：开发库里已有的掌握度会在下一次读取 `/learner` 或反思时按新版本重建（预期行为）。开发库还需要 `make migrate` 应用 8b 的 `4b93dd7c1f27`（本任务没有新迁移）。

---

## 2026-09-29 · P1b 任务 8b：agent 活动公示（ADR 0013 §3）

- **做了什么**：拆成 8b.1–8b.6，用户确认了三点：记忆只存引用、隐藏开关存 localStorage、后台结果用短轮询。完成：`agent_activities` 表和 `app/activity/`；`load_context` 记活动并通过 SSE `activity` 事件推送，`done` 带 `turn_id`；反思记 `reflect_memory` / `grammar_tagging` / `summarize`（失败记 failed，没配模型记 skipped）；`GET /conversations/{id}/activity`（记忆解析成当前内容、KC 名称、`pending`）；前端每条回复下的“私教做了什么”（收起一行 / 展开明细）、`done` 后 60 秒内轮询、设置页“显示”开关；E2E。明细见看板。
- **未完成**：无。明细里的 `/learner` 链接等任务 9 做出页面后再加（`frontend/src/components/chat/turn-activity.tsx` 的 grammar_tagging 分支）。
- **下一步**：任务 9：学习者模型接口 + `/learner` 页面。开工前拆子任务、和用户确认。
- **踩坑**：
  - `streamChat` 原来遇到第一个非 token 事件就结束，加了 `activity` 事件后必须改成读到 done / error 才停。
  - 活动摘要放在消息 `<li>` 里，会破坏 E2E 对整条消息的 `toHaveText` 和正则匹配。现在气泡是 `li > [data-slot=message]`，E2E 的消息选择器都指向它；以后在消息下面加东西，也放在气泡外面。
  - 新建会话时回复可能在会话 id 切换之前就结束，所以 `use-activity` 不在切换时清定时器，而是按会话 id 丢弃过期结果。
  - React lint 不允许在 effect 里直接 setState，所以状态里记着它属于哪个会话，切换时视为空状态。
  - 测试里 `expire_all()` 之后再读 ORM 对象的属性会触发同步懒加载报错（MissingGreenlet），要先把 id 取到局部变量。
  - `mypy` 只检查 `app`（与 CI 一致），`tests/` 里有几个历史遗留的类型错误，不在 CI 检查范围内。
  - 无头 Chromium 没有中文字体，截图里中文是方块，和应用无关。

---

## 2026-09-29 · P1b 任务 8：反思打标 → 证据 → 掌握度；ADR 0013

- **做了什么**：用户要求记住 agent 工具调用的特性、公示 agent 用到的工具 / MCP：写了 ADR 0013（工具调用规范 + 界面公示）、`docs/agent-tools.md`（公开清单）、CLAUDE.md 约束一条、长期记忆一条；界面公示排为任务 8b（每条回复下默认收起、可展开，设置里可隐藏）。任务 8 完成，明细见看板。
- **未完成**：无。
- **下一步**：任务 8b：活动记录表（每步一行：类型、名称、状态、耗时、面向学习者的白名单摘要）；`load_context`、反思（记忆增删改、错误打标）写入活动；SSE 推送对话中的步骤；前端回复完成后再取一次后台结果；设置里可隐藏；更新 `docs/agent-tools.md`。开工前拆子任务、和用户确认。
- **踩坑**：反思输入改了格式（`Learner [u1]:`），E2E 假模型按 `^Learner: ` 匹配，会让记忆 E2E 静默失效，已改。`record_chat_evidence` 的删除用 `RETURNING kc_id`，这样被删掉证据的 KC 也会重算。语音消息的转写文本同样会被打标，prompt 已排除标点和大小写，但转写错误（同音词）仍可能被当成语法错误，任务 8b 公示出来后观察。同一事务里 `now()` 相同，证据按 (created_at, id) 排序重放。

---

## 2026-09-29 · P1b 任务 7：规则文件、BKT、Elo、学习者模型表

- **做了什么**：任务 7 完成。用户选定：BKT 先验按等级差给值、严重度三级（low 不计入）、`skill_estimates` 存 attempts；题目难度由 LLM 按维度打分给先验、Elo 按作答校准。用户要求以后方便改规则 → ADR 0012：规则集中在 `app/adaptive/rules.yaml`（带版本号）；`mistakes` 表改为只追加的 `kc_evidence`，掌握度由证据重放得出，`kc_mastery` 记 `rules_version`。代码在 `app/adaptive/{rules,bkt,elo}.py`，迁移 `612ac223409b`。提交 `8e1796f` 及本次提交。
- **未完成**：无。
- **下一步**：任务 8：反思 schema 加 `mistakes`（kc_id、error_type、severity、original、correction、l1_transfer）和 `used_correctly`；KC 清单渲染进反思 prompt 的固定前缀（id + description + common_errors）；非法 kc_id 丢弃；写入 `kc_evidence`（message_id 用学习者消息 id，要防止反思重试时重复写入）；按受影响的 KC 重放并写回 `kc_mastery`；`rules_version` 变化时的重建时机（建议读取时发现版本不符就重建该用户）。开工前先拆子任务、和用户确认。
- **踩坑**：YAML 行内映射 `{offset: 0.4, description: ..., e.g. ...}` 里的逗号会把描述拆成多个键（extra="forbid" 抓到了），描述要加引号。BKT 连续答对后浮点数会算出正好 1.0，之后永远降不下来，结果要限制在 [1e-4, 1-1e-4]。测试里 commit 之后 ORM 对象过期，再读 `user.id` 会触发 MissingGreenlet，要在 commit 前取出来。

---

## 2026-09-29 · P1b 任务 6 完成：KC 清单审核

- **做了什么**：用户不逐条审核，授权按英语教师的专业标准自审。按“一个 KC 只对应一种技能、一种错误只归一个 KC”重构清单，得到 119 个 KC，改动明细见看板 6.3。ADR 0010 §1 补上规则和 `error_type` 五类枚举。新增例句唯一性测试。
- **未完成**：无。`.claude/state/kc-review.html` 审核页已经过时（还是 118 个的初稿），没用了。
- **下一步**：任务 7：BKT / Elo 纯函数（`app/adaptive/`，只用标准库）+ `kc_mastery`、`mistakes`、`skill_estimates` 表和迁移。开工前先拆子任务、和用户确认。
- **踩坑**：初稿里同一种错误常常挂在好几个 KC 下（如“He can speaks”同时在第三人称和 can 下、逗号连写同时在三个 KC 下），打标时会把证据摊薄；以后改清单时，`test_shipped_error_examples_have_one_owner` 只能查出重复的引号例句，语义上的重叠还要人看。

---

## 2026-09-29 · P1b 任务 6：语法 KC 清单初稿与加载校验

- **做了什么**：任务 6 拆成 6.1–6.3，三个设计问题用户都选了推荐项（`error_type` 用全局五类枚举；清单只收语法；初稿在会话里直接起草）。6.1 `app/adaptive/kc/catalog.py` + lifespan 启动时加载 + 15 个单测；6.2 `app/adaptive/kc/grammar.yaml` 118 个 KC。提交 `c1bf757`。pytest 437、ruff、mypy 通过。
- **未完成**：6.3 用户审核。审核页是本地文件 `.claude/state/kc-review.html`（数据由 `.claude/state/kcs.json` 嵌入，模板 `kc-review.tpl.html`；清单改了之后要重新导出并生成）。没能发布成 Artifact：本会话用 `ANTHROPIC_AUTH_TOKEN` 鉴权，Artifact 需要 claude.ai 登录。
- **下一步**：用户把审核意见（页面“复制审核意见”生成的文本）贴回来 → 改 `grammar.yaml` → 跑 `tests/unit/test_kc_catalog.py` → 提交，任务 6 标 `[x]`；然后任务 7（BKT / Elo 纯函数 + 三张表）。反思 prompt 用的 KC 清单渲染（id + description）留到任务 8 再写。
- **踩坑**：KC 清单用列表而不是以 id 为键的映射，因为 YAML 会静默覆盖重复键，唯一性校验就失效了。

---

## 2026-09-29 · P1a 任务 5：记忆/画像接口与 `/memory` 页面

- **做了什么**：任务 5 完成，P1a（长期记忆）全部完成。后端 `app/api/memory.py` + `tests/integration/test_memory_api.py`（提交 `e975e59`）；前端 `/memory` 页面（`src/components/memory/{memory-app,profile-section,memory-list-section}.tsx`、`src/lib/profile.ts`）、导航、`proxy.ts` 匹配 `/memory`、设置页 `RouteSection` 加入 `reflect`；中英文案；E2E 假模型支持记忆（`e2e/fake_llm.py` 的 `reflection`、`remembered_facts`）和 `e2e/memory.spec.ts`。详见看板完成记录。
- **未完成**：无。没有在设置页加 embedding（`embedding/memory`）路由编辑：计划里任务 5 只要求 `reflect`，而且 `RouteSection` 目前只按对话/语音筛选模型列表，要支持 embedding 需要在 `model-catalog.ts` 加 embedding 分类。没配时按 YAML 的 embedding 默认路由，检索退化为按时间，不影响使用。是否要加由用户决定。
- **下一步**：任务 6（语法 KC 清单：LLM 起草 → 用户审核 + 加载校验），开工前先拆任务、和用户确认。
- **踩坑**：E2E 里不要在回复还在流式输出时离开页面：请求被取消（`llm_usage` 记为 `CancelledError`），这一轮不算完成，也就不会触发反思。等回复完整显示、“发送”按钮回来再跳转。`page.waitForResponse(...).finished()` 对这个 SSE 请求不可靠（会一直等），用界面状态判断。上次会话因为请求体超过 32 MB 中断，改动都还在工作区，接着做即可；本机 zsh 的 `pnpm` 是 nvm 懒加载函数，在 Bash 工具里会无限递归，要用 `~/.nvm/versions/node/v24.14.0/bin/pnpm` 并把该目录加进 PATH。

---

## 2026-09-29 · P1 规划：阶段计划与 ADR 草稿

- **做了什么**：写了 `docs/plans/P1-mvp.md`（Demo 脚本、四个子阶段 P1a 记忆 / P1b 学习者模型 / P1c 背单词 / P1d 入学测、依赖、设计、17 个任务、待确认的 Q1–Q10）和 ADR 0009（长期记忆）、0010（学习者模型）、0011（词库与 FSRS）草稿，状态都是“提议”。看板的 P1 部分已拆好任务。没有改代码。
- **调研结论**（2026-09-29 查 PyPI / GitHub）：py-fsrs 6.3.2 实现 FSRS-6，核心只依赖 typing-extensions，不装 `[optimizer]`；ECDICT 77 万条、66 MB，没有现成小子集，标签词数写在 ADR 0011；LangGraph `AsyncPostgresStore` 在 langgraph-checkpoint-postgres 3.1 里，但语义索引在创建时固定 embedding 函数和维度，和租户各自配置 embedding 冲突，所以推荐自建 `memories` 表；LangMem 自 2025-10 的 0.0.30 后没有新版本，不引入；pyBKT 依赖 numpy / sklearn / pandas，BKT 和 Elo 自己写。
- **确认结果**：用户确认 Q1–Q10 全部按推荐；ADR 0009–0011 改为已采纳，PLAN 已同步。用户同时追加需求“个人能力看板（图表）+ AI 建议 + 直达学习”，写成计划 §7.5 和子阶段 P1e（任务 17–19，原 Demo 实测顺延为 20），Q11–Q14 待确认。
- **未完成**：Q11–Q14（看板图表组合、建议生成方式、首页、图表库）等用户确认。
- **任务 0 完成**：11C 第 3、4 条（详见看板完成记录）。
- **Q11–Q14**：用户确认全部按推荐。
- **任务 2 完成**：画像表、记忆表、记忆服务层（详见看板完成记录）。
- **任务 3 完成**：`load_context` 节点，学习者上下文走 `UntrackedValue` 通道，不进 checkpoint（详见看板和 ADR 0009 落地记录）。
- **任务 4 完成**：后台反思（详见看板完成记录和 ADR 0009 落地记录）。
- **下一步**：任务 5，记忆/画像接口（`app/api/memory.py`：GET/PATCH 画像、记忆列表、PATCH/DELETE 单条、清空）+ 前端 `/memory` 页面（画像表单、事实列表可编辑删除、会话摘要列表）+ 设置页路由编辑器加入 `reflect`（`frontend/src/components/settings/route-section.tsx` 的 `RouteTask`）+ E2E：聊天 → 记忆出现 → 删除 → 新会话不再使用（假模型需要能返回一条记忆，可以按消息内容决定）。
- **踩坑**：工具函数别以 `test_` 开头（`test_clip` 被测试模块导入后会被 pytest 当成测试收集），已改名 `silent_clip`。pgvector 的 alembic autogenerate 会写出 `pgvector.sqlalchemy.vector.VECTOR()` 却不加 import，要手动改成 `from pgvector.sqlalchemy import Vector`。LangGraph 状态里有不想持久化的中间值时用 `Annotated[T, UntrackedValue(T)]`；图的 input/output schema 要另设为 `MessagesState`，否则调用方的类型要求带上这个字段。

---

## 2026-09-29 · 11B 实测：语音转写接入硅基流动

- **做了什么**：用户实测 11B。看图（中转站 gpt-6-sol）和 PDF 提取正常；语音一路排查：中转站没有 `/audio/transcriptions`（404）→ 本地 speaches（要 `PROVIDER_ALLOW_PRIVATE_NETWORKS=true`，容器里地址是 `http://asr:8000/v1`）→ 第一段录音 -60 dB 几乎静音，Whisper 编出一串“ლ”，是麦克风问题 → 想换 Groq，发现 Groq 屏蔽大陆 IP（直连 403，经代理 401），后端又有意不走代理 → 新增硅基流动预设（11B.7），用户实测中英文都转写正确。顺带修了测试会读开发者 `.env` 的问题。CI 全绿。
- **未完成**：11C 五个体验问题（看板里有），待用户决定做不做。
- **下一步**：**用户已选 P1**（11C 暂缓）。新会话先读 `docs/PLAN.md` §二·五、§三、§四 P1，参照 `docs/plans/P0-skeleton.md` 写 P1 阶段计划和 ADR，拆任务后和用户确认。原先的备选是：先做 11C，还是直接规划 P1（Supervisor 主图、长期记忆、FSRS 背单词、CEFR 入学测、自适应引擎第一版）。P1 开工前要先写阶段计划（参照 `docs/plans/P0-skeleton.md`）和相关 ADR，拆任务写进看板，确认后再动手。
- **踩坑**：国外模型 API 的地区屏蔽只在直连时出现，开发机上经代理测试会漏掉，要从后端容器里测（`httpx`，`trust_env=False`）。Whisper 对静音会编造文字，判断转写质量前先用 `ffmpeg -af volumedetect` 看音量。本机的 gh 装在 `~/.local/bin`，已登录。

---

## 2026-09-29 · 任务 13 README

- **做了什么**：`README.md`（英文）+ `README.zh-CN.md`（中文），顶部互相链接，带 CI 徽章；如实写 P0 能做什么 / 还没做什么，Docker 快速开始、模型配置（三个任务、本机模型服务与 SSRF 开关、可选本地语音转写）、本地开发、mermaid 架构简图 + 目录说明 + ADR 链接、部署注意事项、贡献。界面名称按 i18n 文案核对（中文界面是“对话”“语音转文字”）。`CLAUDE.md` 补了“常用命令”。从 GitHub 新 clone，用独立的 compose 项目名照 README 从零跑通（详见 PROGRESS 13.4）。
- **未完成**：无。11B（附件）仍待用户用真实模型实测。
- **下一步**：用户实测 11B；之后确认 P0 收尾，按 PLAN 规划 P1（开工前先拆任务写进看板）。
- **踩坑**：compose 文件固定了 `name: lingo-agent`，同一台机器上再 clone 一份直接 `make up` 会接管原来的容器和数据卷，验证时要设 `COMPOSE_PROJECT_NAME` 并换端口。zsh 里 `echo ======` 会报 `= not found`（`=word` 会被展开成命令路径）。

---

## 2026-09-29 · 任务 12 推送到 GitHub，修 CI

- **做了什么**：用户确认保留提交邮箱和文档里的环境细节后，添加 remote `git@github.com:YangD1/lingo-agent.git`（公开仓库）并推送 main。第一次 CI：frontend、docker 通过，backend、e2e 在 Set up job 失败（`astral-sh/setup-uv@v10` 不存在），改为 `@v10.2.0`。第二次运行只有 backend 的 pytest 失败；本地去掉代理变量、TZ=UTC 重跑，复现出测试在做真实 DNS 解析（`test_chat_attachments.py` 没有 DNS 桩），改为在 `tests/conftest.py` 全局加 `public_dns`。但第三次仍失败；装 gh（官方二进制放到 `~/.local/bin`）并登录后读日志，真正原因是 `test_chat_attachments.py` 的 `not_ready` 用例在和后台处理任务赛跑，已改成确定性写法。
- **未完成**：第二次 CI 运行的结果；backend 和 e2e 的测试步骤在 GitHub 上还没真正跑过。
- **下一步**：CI 全绿后把任务 12 标 `[x]`，然后做任务 13 README。
- **踩坑**：CI 失败先读日志再猜——`gh run view <id> --log-failed`。全局 autouse fixture 不要依赖 `monkeypatch`，否则会改变各模块 fixture 的撤销顺序（`_clear_caches` 报 `cache_clear` 不存在）。本机 gh 不可用，但仓库公开，可以不带认证调用 `api.github.com/repos/.../actions/runs` 和 `check-runs/<job id>/annotations` 查状态和失败原因（日志下载需要认证）。setup-uv 从 v8 起没有浮动的主版本标签，要写完整版本号。

---

## 2026-09-29 · 任务 12 GitHub Actions CI

- **做了什么**：`.github/workflows/ci.yml`，四个 job（backend / frontend / docker / e2e），每次推送 main 和每个 PR 都跑（用户选 A）；`make ci`；P0 计划 §10 已同步；`e2e/run_backend.py` 的数据库地址改为从 `E2E_ADMIN_DB` 推导。actionlint 通过；在新 clone 的仓库和全新数据库上模拟了 backend、frontend、e2e 三个 job，全部通过。
- **未完成**：GitHub 上的实际运行。仓库还没有 remote，要用户建仓库并推送。第一次运行时注意：Action 版本号来自子代理查询；GHA 的 docker 缓存第一次是冷的；e2e 在 GitHub runner 上的耗时还不知道。
- **下一步**：任务 13 README（英文 + zh-CN）+ CLAUDE.md 的“常用命令”。
- **踩坑**：zsh 里 `pnpm` 是懒加载 nvm 的函数，设了 PATH 也会递归调用，要先 `unset -f pnpm`；`timeout` 后面不能接 shell 内建的 `command`。

---

## 2026-09-29 · 11B.6 附件 E2E、speaches、全栈冒烟（11B 完成）

- **做了什么**：
  - 假模型支持看图识别（function calling）、回复中说明看到几张图、`/audio/transcriptions`。
  - E2E `attachments.spec.ts` 6 个用例，完整套件 21 个全部通过；录音、canvas 压缩、粘贴 / 拖拽这次在真实 Chromium 里验证了。
  - compose profile `asr`（speaches）+ `make asr-up/asr-down`，真实语音转写测试通过。
  - 重建镜像，全栈冒烟通过。细节见看板 11B.6a–d。
- **未完成**：用户实测。用户要在 `.env` 里设 `PROVIDER_ALLOW_PRIVATE_NETWORKS=true`（compose 里的后端要访问 `http://asr:8000/v1`），访问不了 huggingface.co 时再设 `ASR_HF_ENDPOINT=https://hf-mirror.com`，然后 `make up`。
- **下一步**：任务 12 GitHub Actions CI（backend / frontend / docker build）。E2E 进 CI 时注意：Playwright 的 webServer 用 `uv run --project ../backend` 拉起假模型和后端，需要 postgres 服务；附件用例用 Chromium 假麦克风参数。
- **踩坑**：
  - 容器用不了宿主机只监听 127.0.0.1 的代理（Clash 7890），HF 只能走镜像站。
  - 旧 backend 镜像配新 YAML 会因为 `extra_forbidden` 一直重启：改了 YAML 结构后要重建镜像。
  - Playwright 拿不到由 Blob 组成的 multipart 请求体。
  - eslint 的 hooks 规则会把 `use*` 名字的 E2E 辅助函数当成 React hook。
  - zsh 不会对 `$C` 这类变量做分词，复杂的 curl 流程改用 Python 脚本写。

---

## 2026-09-29 · 11B.5 前端附件输入与展示

- **做了什么**：11B.5a–e 全部完成（细节见看板 11B.5 的“完成记录”）。前端：附件按钮 / 粘贴 / 拖拽 / 录音，附件卡片（上传中、识别中带页数进度、失败可重试、查看和修改识别结果、移除），附件未就绪时不能发送，消息里显示图片 / 音频 / 文档；设置页可以编辑 chat、vision、asr 三个路由；中英文案和 17 个新错误码。typecheck、lint、build、Vitest 93、Playwright 15 全部通过。
- **未完成**：录音、canvas 压缩、粘贴和拖拽只在 jsdom 里测过逻辑，还没有在真实浏览器里跑过。
- **下一步**：11B.6：`e2e/fake_llm.py` 支持看图回显（能看到 image 块就回显）和 `/audio/transcriptions`；E2E 用 `data-testid="attachment-input"` 的隐藏 file input 调 `setInputFiles` 上传；覆盖图片、文档（含扫描版 PDF）、语音文件（录音可以用 Chromium 的 `--use-fake-device-for-media-stream` + `--use-fake-ui-for-media-stream`）、未配置 vision 时的“去设置”、修改识别结果；compose 加 `asr` profile（speaches）并实测内存；重建镜像交给用户实测。
- **踩坑**：设置页有多张路由卡片后，E2E 里按名字查找按钮会命中多个元素，要先用 `getByTestId("route-<task>")` 限定范围。
- **注意**：上次会话因为请求超过 32MB 而中断（对话里累积了太多图片）。做 11B.6 的界面验证时尽量少截图，或者截小图。

---

## 2026-09-29 · 11B.4 附件接入对话

- **做了什么**：上次会话写完 11B.4 代码和测试后因请求过大中断，本次修复测试（残留的一行乱码；录制假模型的 `calls` 字段被 pydantic 复制导致记录为空）并全量验证：pytest 367、ruff、mypy(app) 通过。细节见看板 11B.4。
- **未完成**：无（11B.4 已完成）。`tests/unit/test_vision_and_asr.py:129` 有之前就存在的 mypy 报错（`make lint` 只检查 app，不影响）。
- **下一步**：11B.5 前端（附件按钮 / 粘贴 / 拖拽 / 录音、附件卡片轮询、消息内展示、设置页 vision/asr 路由、中英文案）。发送接口：`POST /conversations/{id}/messages` 的 body 为 `{content, attachment_ids}`；错误码 404 `attachment_not_found`，409 `no_vision_model` / `attachment_not_ready` / `attachment_sent`，422 `invalid_attachments` / `too_many_images`；历史接口每条消息带 `attachments`（AttachmentOut）。
- **踩坑**：pydantic 模型（包括 BaseChatModel 子类）的 `list` 字段会在校验时复制，想共享可变对象要用 `Any`。

---

## 2026-09-29 · 11B.3 附件派生文本

- **做了什么**：vision 路由（只认显式配置）、`asr` 一节 + `get_asr()`、图片 / 语音 / PDF（含扫描页）/ DOCX 的处理函数，以及对应测试。细节见看板 11B.3。
- **未完成**：11B.4 对话接入：
  - `app/api/chat.py` 的 `MessageIn` 加 `attachment_ids`，在 `start_turn` 里校验：附件属于同一会话、状态为 ready、还没发送；单条消息最多 5 个，其中图片最多 4 张；正文为空时必须有语音附件。
  - `app/chat/turn.py` 由后端生成 HumanMessage 的 id，并写入 `attachments.message_id`。
  - `app/agents/chat_graph.py` 的 tutor 节点组装附件：通过 ChatContext 传一个附件读取器，按消息 id 查附件；当前轮带图片时改用 `vision` 路由。
  - `get_history` 返回附件信息。
- **下一步**：11B.4 → 11B.5 前端 → 11B.6 E2E、speaches compose、重建镜像。
- **踩坑**：
  - 手写 PDF 时，`io.BytesIO(初始内容)` 的写入位置在 0，后续写入会覆盖文件头。
  - alembic 的 `op.drop_constraint` / `create_check_constraint` 也会套用 naming convention，名字要包在 `op.f()` 里，否则会变成 `ck_表_ck_表_列`。
  - TaskGroup 抛出的是 ExceptionGroup，处理器只认 `ProcessingFailed`，所以要先从组里取出来。
  - OpenAI 已推荐改用 `gpt-transcribe`，`whisper-1` 等将在 2027-02 下线（第三方站点报道，OpenAI 文档确认了推荐模型）。

---

## 2026-09-29 · 11A 收尾，11B.1 设计，11B.2 附件存储与接口

- **做了什么**：
  - 用户实测 11A 通过。
  - 11B 设计：ADR 0008 已采纳（图片 + 语音 + 文档（含扫描版 PDF），“两者结合”，PostgreSQL bytea，进程内后台处理 + 轮询），PLAN 已同步。
  - 11B.2 后端附件：`backend/app/attachments/`（sniff、images、processor、handlers、service）+ `app/api/attachments.py` + 迁移；app.state 上有 `attachment_processor`（`main.py` 的 `init_state` 创建，lifespan 启动时执行 `fail_interrupted`，退出时 `stop`）；测试夹具同步。
- **未完成**：11B.3 派生文本。在 `app/attachments/handlers.py` 的 `default_handlers()` 里加 image / audio / pdf / docx 处理函数，需要：provider 层的 `llm.vision` 路由 + `ImageReading`，`asr` 一节 + `get_asr()`，`llm_usage.audio_seconds`，pypdfium2 + python-docx。处理函数运行在后台任务里，需要**自己加载租户的 provider 上下文**（`load_provider_context(session, job.tenant_id)`），调用看图模型时要持有 `processor.vision_slots`，所以处理函数需要能拿到 processor（可以用闭包或工厂函数注入）。
- **下一步**：11B.3 → 11B.4 对话接入 → 11B.5 前端 → 11B.6 E2E 与部署。
- **踩坑**：
  - `deferred(mapped_column(LargeBinary))` 会让 autogenerate 生成 nullable=True，要显式写 `nullable=False`。
  - MP3 帧同步只看 11 位的话，UTF-16 BOM（FF FE）也能匹配上，要加 Layer III 判断。
  - Pillow `draft()` 要求返回的尺寸在**两条边**上都不小于请求值，要按原图比例算请求尺寸，不能传正方形。
  - 测内存峰值要在新进程里测，否则前面造数据时的峰值会掩盖结果。
  - 迁移还没在开发库（:3000 那套）上执行：11B.6 重建镜像时，后端启动会自动执行。

---

## 2026-09-28 · 11A.8 聊天消息渲染 Markdown

- **做了什么**：用户反馈模型回复里的 `**加粗**` 原样显示。原因是 `message-list.tsx` 直接输出纯文本。新增 `frontend/src/components/chat/markdown.tsx`（react-markdown + remark-gfm + remark-cjk-friendly/parseOnly），只用于 assistant 消息；单测 5 个 + E2E 1 个；前端镜像已重建。
- **未完成**：11A.6 仍在等用户用中转站实测。用户提出“用户消息支持多模态输入”，已记为看板任务 11B，需要先设计（PLAN + ADR：消息内容结构、上传存储、模型能力路由），还没开始。
- **下一步**：等用户确认 11A.6 → 11B 设计 或 任务 12 CI（由用户定顺序）。
- **踩坑**：
  - react-markdown 会给自定义组件传 `node` prop，直接 `{...props}` 展开会变成 DOM 属性，要先去掉（`markdown.tsx` 的 `styled()`）。
  - 回复里有列表后，E2E 的 `locator("li")` 会把列表项也算成消息，改用 `:scope > li`。
  - 用户消息仍需 `whitespace-pre-wrap`；assistant 消息不能加，否则块元素之间的 `\n` 会多出空行。

---

## 2026-09-28 · P0 任务 11A.4–11A.5（前端：建连接选默认模型、路由下拉编辑）

- **做了什么**（每项单独提交）：
  - 11A.4 连接卡片：新建连接后自动拉取模型列表，预选推荐模型，可搜索，失败时显示厂商原因并可手填；测试按钮直接测框里的模型。新增 `ui/autocomplete.tsx`（Base UI **Autocomplete**，值就是输入框的文字）、`lib/models.ts`（+单测）；`fake_llm.py` 加 `/v1/models`。
  - 11A.5 `chat-route-section.tsx` 重写：显示实际生效的链和来源；编辑改为每行“连接下拉 + 模型搜索”，可增删、调顺序。`settings/model-catalog.ts` 共用。E2E 改为不设路由就能聊天，新增拉取失败的用例。
- **未完成**：11A.6 收尾——全量 `make test`/`make lint`，重建镜像 `make up`，请用户用自己的中转站实测。
- **下一步**：11A.6，然后任务 12 CI。
- **踩坑**：
  - Base UI 弹层打开时会把页面其余部分设为 `aria-hidden`，Playwright 按角色定位会找不到按钮：手填后先按 Tab 关掉弹层。
  - Playwright 对整个 `list` 用数组形式的 `toHaveText`，只有列表里恰好一项时才成立；多项要对 `getByRole("listitem")` 断言。
  - 前端没有装 prettier，`pnpm exec prettier` 会找不到命令（之前一次还卡住了）；格式只靠 eslint。
  - Playwright 的 `reuseExistingServer` 会复用端口上已有的旧 fake_llm（没有 `/v1/models`），跑 E2E 前先 `fuser 8100/tcp 8101/tcp 3100/tcp` 确认端口空闲。

---
## 2026-09-28 · P0 任务 11（docker-compose 全栈、.env.example、Makefile）→ 完成

- **做了什么**（每个子任务单独提交）：
  - 11.1 `backend/Dockerfile`：启动时迁移、非 root、HEALTHCHECK。
  - 11.2 `frontend/Dockerfile`：standalone；`BACKEND_URL` 构建时和运行时都注入；`pnpm start` 改为 `scripts/start-standalone.mjs`，E2E 也跑它；限制 `next build` 的 worker 数和堆内存。
  - 11.3 `docker-compose.yml`：新增 backend、frontend 服务；只有前端对外，其余都只绑 127.0.0.1；neo4j、redis 放进 profile。
  - 11.4 `Makefile`（`make help` 列出全部目标）+ `.env.example`。
  - 11.5 独立 compose 项目从零走完 Demo，包括降级、重启后数据还在、密钥轮换、`host.docker.internal`。细节见看板和 P0 计划 §16。
- **未完成**：无。仍待用户手动：在设置页填真实 key 做一次冒烟（可以直接 `make env && make up` 后在 :3000 上做）。
- **下一步**：任务 12 GitHub Actions CI。按 P0 计划 §10：backend job（postgres service，`uv sync --locked` → ruff → format check → mypy → pytest）、frontend job（lint、typecheck、Vitest、build）、E2E job（需要 postgres + uv + pnpm + chromium）、docker job（`docker compose build`）。
- **踩坑**：
  - **本机做重构建会把 Windows 拖崩**：两次 docker 构建耗尽了 Windows 的提交内存（vmmemWSL 约 10GB + MuMu 模拟器 7.7GB，上限 39.7GB），WSL 和模拟器一起崩溃。WSL 内部的 cgroup 上限和看门狗都没用，因为 vmmem 会随 Linux 页缓存一起涨。用户已设 `.wslconfig`：`memory=8GB`、`swap=4GB`、`autoMemoryReclaim=dropCache`，页面文件改为系统管理。重构建前用 `powershell.exe` 查一下 Windows 可用提交内存（`Win32_OperatingSystem.FreeVirtualMemory`）。证据在 Windows 事件日志 Resource-Exhaustion-Detector 2004。
  - 崩溃时 pnpm 缓存里留下了写到一半的文件，报 `ERR_PNPM_CMD_SHIM_PARSE_MANIFEST`；用 `docker buildx du --filter type=exec.cachemount` 找到它，再用 `docker buildx prune --filter id=…` 只清这一个。
  - 不要写 `# syntax=docker/dockerfile:1`：BuildKit 解析它时直连 Docker Hub，本机代理环境下会超时。`docker manifest inspect` 同理；`docker pull` 走守护进程的代理，是通的。
  - uv 0.11.8 没有 `…-python3.12-bookworm-slim` 组合镜像，改用 `COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv`。
  - pnpm 12 不支持 `-s`；zsh 不会把 `$VAR` 按空格拆成多个参数，多步 shell 流程写成 bash 脚本再跑。
  - `e2e/fake_llm.py` 只监听 127.0.0.1，容器里访问不到；冒烟时在 docker 网络里用 `uvicorn.run(fake_llm.app, host='0.0.0.0')` 启动它。

---
## 2026-09-28 · P0 任务 10.5–10.8（聊天页、设置页、E2E、收尾）→ 任务 10 完成

- **做了什么**（每项单独提交）：
  - 10.5 聊天页：`/chat?c=<id>`（History API，新建会话不重新挂载）；会话延迟创建，开流前被拒绝就删掉空会话并把文字还回输入框；`no_llm_configured` 引导去设置；停止生成标注“未保存”。核心在 `components/chat/use-chat-session.ts`。
  - 10.6 设置页 `components/settings/`：连接（预设/自定义、测试、替换 key、删除）、chat 路由（fallback 链，可恢复默认）、用量表（7/30/90 天，手动刷新）。新增 `ui/native-select.tsx`。
  - 10.7 E2E 共 11 个（auth 3、chat 3、settings 2、i18n 3），本次补了“登录后在应用内切换语言”。
  - 10.8 全量检查 + 经 Next 代理的 curl 全栈冒烟（SSE 逐块到达）；P0 计划 §8/§10/任务表已同步。
- **未完成**：无（任务 10 已 `[x]`）。待用户手动做一次真实 key 冒烟（设置页填 key → 聊天）。
- **下一步**：任务 11 docker-compose 全栈 + `.env.example` + Makefile（`gen-key` / `rotate-credentials`）。前端 Dockerfile 要把 `BACKEND_URL` 作为 **build arg**（rewrites 在构建时确定），并用 `output: "standalone"`（`next.config.ts` 现在还没加）。
- **踩坑**：
  - Next 的 rewrites 目标在 `next build` 时写死：手动起生产服务冒烟时忘了带 `BACKEND_URL` 构建，结果代理指向了 :8000。
  - 在 `( … &)` 子 shell 里调 `pnpm` 会命中 zsh profile 里的 nvm 懒加载函数（`_load_nvm` not found），要用绝对路径 `~/.nvm/versions/node/v24.14.0/bin/pnpm`。
  - shadcn base-nova 的 `CardTitle` 是 `div` 不是 heading，E2E 用 `getByText` 定位。
  - WSL 里的 headless chromium 没有中文字体，中文截图显示方框，只是环境问题。
  - 后端历史接口里 assistant 消息的 id 是 LangChain 的 run id（`lc_run--…`），不是 UUID；前端只把它当不透明的 key，暂不影响。

---
## 2026-09-28 · P0 任务 10.1–10.4（前端脚手架、i18n、API/SSE 客户端、鉴权）

- **做了什么**（每项单独提交）：
  - 10.1 Next 16.3.6 脚手架 + shadcn（base-nova）+ Vitest + Playwright。**实测 SSE 经过 Next rewrites 时会被 gzip 缓冲**（dev 和 start 都会），后端 `start_turn` 追加 `Cache-Control: no-transform` 后修复（`fix(chat)`），不需要走备选方案；abort 能经过代理传到后端。
  - 按用户决定，把后端**所有**错误统一为 `{detail:{code,message}}`（`app/api/errors.py`，包括全局 handler），ADR 0003 §3。
  - 10.2 i18n：next-intl，语言存在 cookie 里，不做 URL 前缀（ADR 0006）。和原计划不同：语言协商放在 `request.ts` 里，proxy 只负责鉴权。
  - 10.3 `lib/api.ts`、`lib/sse.ts`（async generator）。
  - 10.4 登录和注册页、`proxy.ts`（乐观检查）+ `(app)` 布局用 `/auth/me` 做权威校验 + `/session-expired`（防止重定向死循环）。E2E 基础设施：`frontend/e2e/run_backend.py` + Playwright 双 webServer。
- **未完成**：10.5 聊天页（`src/app/(app)/chat/page.tsx` 现在是占位）、10.6 设置页（`(app)/settings/page.tsx` 占位）、10.7 剩下的部分（`e2e/fake_llm.py` 和聊天/设置的 E2E 用例）、10.8 收尾。
- **下一步**：10.5 聊天页，用 `streamChat()`；409 `no_llm_configured` 引导去 /settings。
- **踩坑**：
  - 在 Bash 工具里用 `pkill -f <模式>` 或 `pgrep -f` 会匹配到**当前 shell 自己的命令行**，把自己杀掉（exit 144）。改用 `fuser -k <port>/tcp`。
  - FastAPI 的 SSE 接口体在响应头发出之后才运行，所以响应头只能在依赖里设置；而且是 `raw.extend` 追加，不是覆盖。
  - Next 16.3 自带文档写的是 `unstable_doesProxyMatch`，但实际导出的只有 `unstable_doesMiddlewareMatch`。
  - `PageProps<"/login">` 这类路由类型要先运行 `next typegen`，所以 typecheck 脚本改成了 `next typegen && tsc --noEmit`。
  - Next 的路由播报器（`__next-route-announcer__`）也是 `role=alert`，E2E 要把定位范围限定在表单内。
  - `pnpm add` 遇到带构建脚本的新依赖时，会往 `pnpm-workspace.yaml` 的 allowBuilds 里写占位值 `set this to true or false`，要手动改成 true 或 false。
  - 在一个测试文件里 import 另一个 `*.test.ts`，会把那个文件的测试重复注册一遍；公共的测试辅助函数放在 `src/test/`。
  - `frontend/` 目录下的 .py 文件要用 `--config ../backend/pyproject.toml` 跑 ruff。
  - 这个环境访问不了 GitHub 和 next-intl.dev，查文档就直接读 `node_modules` 里的 README、类型定义和源码。

---


## 2026-09-28 · P0 任务 9 完成（9.4 冒烟与两个断开相关的修复）

- **做了什么**：
  - 真实 uvicorn + 本地假 OpenAI 兼容服务（逐字慢速流式输出，支持 `stream_options.include_usage`）+ curl 端到端冒烟。走的是真实的 openai SDK、SSRF 防护过的传输层、stream_usage 和用量回调。验证了：注册 → 未配模型时返回 409 → 建连接和路由 → 流式回复（usage 42/16）→ 客户端中途断开 → 立即重发返回 200 → 历史 → `/tenant/usage`。
  - **发现并修复两个 bug**（各自单独提交，都带修复前失败的回归测试）：
    1. `fix(usage)`：被取消的调用漏记。`UsageRecorder` 改为同步 handler，并设 `run_inline=True`。
    2. `fix(chat)`：客户端断开后，**上游模型仍然生成完整回复**（租户白付费）。`stream_reply` 改为在独立 task 里跑图，断开时显式 cancel，并在 shield 的 scope 里等它清理完；tutor 节点改用 astream 再合并 chunk，让取消能通知到回调。
  - 同步了 ADR 0003（改用 fastapi.sse、开流前返回的 404 和 409 错误码、断开的实现细节）、ADR 0005（被取消的调用怎么记的两个条件）、P0 计划（sse-starlette 标为不再使用、§6.3）。
  - 全部 208 个测试通过，ruff 和 mypy strict 都干净。
- **未完成**：无。Next rewrites 转发 SSE 时是否会缓冲，留到任务 10 验证（ADR 0003 里的已知风险）。
- **下一步**：任务 10 frontend（Next 16 + shadcn、登录和注册、聊天页、模型设置页含用量表、SSE 客户端、proxy.ts）。开工前先拆分子任务，和用户确认。
- **踩坑**：
  - **anyio 的取消是电平触发的**：在已取消的 scope 里，每一个会挂起的 await 都会再被取消一次。第三方库 finally 里的清理 await（比如 LangGraph 取消节点 task 的那部分）也会被打断，所以要自己管理子 task 的生命周期。普通 asyncio 的 `task.cancel()` 是边沿触发的，没有这个问题。进程内对照实验的脚本思路：anyio.move_on_after 与 task.cancel() 各跑一次，看模型是否中止。
  - `ainvoke` 被取消时不会调用 `on_llm_error`（内部 gather 直接抛出），只有 `astream` 会。以后可能被用户取消的模型调用都用 astream。
  - pydantic 模型的 `list[str]` 字段会在校验时被复制，测试想观察的可变对象要声明成 `Any`。
  - 冒烟和测试共用 `lingo_test`：跑一次全量测试就会 TRUNCATE 冒烟数据，冒烟要在测试之后重新注册。
  - zsh 不会对未加引号的变量做分词，`-H $J` 这种写法会把整个 header 当成一个参数，要写成 `-H "$CT"`。
  - 清空一个正被别的进程写入的日志（`: > file`）后，文件前面会变成一段空字节，grep 会把它当二进制文件跳过，要用 `strings` 看。

---

## 2026-09-28 · P0 任务 9 进行中（9.3 完成）

- **做了什么**：
  - `app/chat/turn.py`：`TokenEvent` / `DoneEvent` / `ErrorEvent`、`title_from`（空白压缩后取前 40 个字符）、`begin_turn`（设标题并刷新 updated_at，然后 **commit**，流式期间不占数据库事务）、`stream_reply`（只转发 tutor 节点的 AIMessageChunk；累加 usage；异常时发 `llm_unavailable`，不泄漏厂商错误文本；metadata 带 user_id，tags 为 `["chat"]`）。
  - `app/chat/locks.py`：`ConversationLocks`（进程内非阻塞锁），在 `create_app` 里挂到 `app.state`。
  - `app/api/chat.py`：`start_turn` yield 依赖（依次做：归属检查返回 404 → 加载 ctx 并解析 chat 路由，失败返回 409 `no_llm_configured` → 加锁，失败返回 409 `conversation_busy` → begin_turn → yield，finally 释放锁）；`send_message` 用 `EventSourceResponse` 输出 SSE，事件名即 event 字段，data 为 JSON。
  - 新增 `tests/integration/test_chat_send.py`（10 个用例）：token 之后是 done、done.message_id 和历史里的 id 一致、标题和排序、llm_usage 记到 user 和会话、主模型在出第一个 token 前失败时切到备用模型（端到端 usage 两行）、中途失败发 error 事件且只保留用户消息、失败后锁已释放可以重试、未配模型返回 409 且不入库、会话忙返回 409、越权返回 404、长度校验返回 422。
  - 全部 202 个测试通过，ruff 和 mypy 都干净。
- **下一步**：9.4，用真实 uvicorn + curl 冒烟（包括客户端中途断开后锁会释放），同步 ADR 0003 / P0 计划（sse-starlette 换成 fastapi.sse、409 的错误码）。
- **踩坑**：
  - **FastAPI 内置 SSE 在执行接口体之前就已经发出 200 响应头**（接口体在 producer task 里跑，见 `fastapi/routing.py` 约第 553–612 行），所以 404 和 409 必须在依赖里抛。yield 依赖默认挂在 request 级的 exit stack 上，流结束或断开后才退出，锁放在这里一定会被释放。
  - 模型按 `(tenant, task, version)` 缓存，测试里中途换假模型后要 `llm.reset_caches()`。
  - `/auth/me` 的返回结构是 `{user: {...}, tenant: {...}}`。

---

## 2026-09-28 · P0 任务 9 进行中（9.2 完成）

- **做了什么**：
  - `app/chat/service.py`：`ConversationNotFoundError`（不存在和不是自己的会话不作区分）、`thread_config`、`list_conversations`（按 updated_at 倒序）、`create_conversation`、`get_owned_conversation`、`to_chat_messages`（只返回 user 和 assistant 消息，内容用 `.text` 拍平成纯文本）、`get_history`、`delete_conversation`（先删 checkpoint，再删行）。
  - `app/api/chat.py`：`GET/POST /conversations`、`GET /conversations/{id}/messages`、`DELETE /conversations/{id}`；访问别人的会话一律返回 404。
  - `app/deps.py` 新增 `ChatGraphDep`。
  - conftest 拆出 `app` fixture（带真实的 Postgres checkpointer），`client` 基于它建。
  - 新增 `tests/integration/test_chat_api.py`，共 7 个用例。全部 192 个测试通过，ruff 和 mypy 都干净。
- **下一步**：9.3 发消息 SSE。
- **踩坑**：删除用户时，会话行会级联删掉，但 **checkpoint 里的消息会变成孤儿**（和“个人租户变孤儿”是同一类问题）。以后做“注销账号”时，要先逐个会话调 `adelete_thread`。

---

## 2026-09-28 · P0 任务 9 进行中（9.1 完成）

- **已确认的决定**：SSE 用 FastAPI 0.141 内置的 `fastapi.sse.EventSourceResponse`（支持 POST，自带 keepalive），不再引入 sse-starlette；没配模型时在开流前返回 409 `no_llm_configured`；同一会话正在生成时再发送返回 409 `conversation_busy`，用进程内锁，多 worker 时改用 advisory lock，放到 P4。
- **做了什么（9.1）**：
  - `app/agents/chat_graph.py`：`ChatContext(providers)`、`tutor` 节点、`build_chat_graph(checkpointer)`、`ChatGraph` 类型别名。system prompt 每次调用时拼在最前面，不存进会话，所以改提示词对老会话也生效。
  - `app/prompts/__init__.py`（`load_prompt`）和 `tutor_system.md`。
  - `app/db/migrate.py` 新增 `create_checkpointer_pool`（autocommit、dict_row、prepare_threshold=0）。settings 和 `.env.example` 新增 `CHECKPOINT_POOL_MAX_SIZE=4`。
  - lifespan 负责打开连接池，建好 `app.state.chat_graph`，关闭时关连接池；checkpoint 表仍由 migrate 创建。
  - conftest 在每个测试后同时 TRUNCATE checkpoint 表（保留 `checkpoint_migrations`）。
  - `tests/integration/test_chat_graph.py` 共 4 个用例：多轮对话按 thread 累积；system prompt 发给模型但不入库；token 来自 tutor 节点；**checkpoint 三张表（包括解码后的 blob）里都没有 key**。
  - 全部 185 个测试通过，ruff 和 mypy 都干净；用真实 lifespan 冒烟通过。
- **下一步**：9.2 会话 CRUD（`app/chat/service.py`、`app/api/chat.py`）。
- **踩坑**：
  - **反向验证**：把 key 放进 `configurable` 后，“key 不入 checkpoint”的测试会失败，因为 LangGraph 会把 configurable 写进 checkpoint 的 metadata。这印证了 ADR 0004 的判断：ctx 只能走运行时 context。
  - PreToolUse 钩子会拦截 `sk-live-...` 这种形状的测试值，改用不像厂商 key 格式的标记串。
  - `graph.astream` 的返回类型覆盖了所有 stream_mode，在 messages 模式下要用 isinstance 把 metadata 收窄成 dict，mypy 才能通过。
  - 用户要求按关键节点提交，方便事后 review 和学习。任务 1–8 是事后按主题拆成 8 个提交补上的，中间的提交不保证能单独运行；从 9.1 开始，每个子任务单独提交一次。

---

## 2026-09-28 · P0 任务 8 完成（第 5 步 llm_usage）

- **做了什么**：
  - `app/usage/recorder.py`：
    - `UsageLabels`、`UsageRecord`、`UsageRecorder`：`on_chat_model_start` 按 run_id 记下开始时间和从 metadata 取到的 id；`on_llm_end` 从 `usage_metadata` 取 token 数；`on_llm_error` 只记异常类名。
    - `set_usage_sink`、`submit_usage`、`make_recorder`。
    - 方案按用户确认的 A：缺少 `user_id` 或 `conversation_id` 时照常记录，该列留空；会话 id 也可以从 LangGraph 的 `thread_id` 取。
  - `app/usage/writer.py`：`UsageWriter`（`submit`、`start`、`stop`、`flush`），攒满或定时批量写库；队列满时丢弃并计数；写库失败时 writer 继续运行。
  - `app/usage/service.py`：`summarize_usage`；`app/api/usage.py`：`GET /tenant/usage`。
  - `llm.py`：`build_chat_model` 新增 `callbacks` 参数，默认 `stream_usage=True`；`get_chat_models` 给每个模型挂 recorder，并按链中位置标 `is_fallback`。`CallParams` 白名单加了 `stream_usage`。
  - 连接的 `/test` 也会记录用量（task 为 `connection_test`）。
  - `require_tenant_manager` 和 `Manager` 从 `api/providers.py` 移到 `app/deps.py`。
  - lifespan 负责启动 writer、安装 sink；关闭时先卸载 sink，再在 5 秒内把队列写完。
  - ADR 0005 A 节：状态改为 `status` 加 `is_fallback`，补了实现细节。
  - 新增 `tests/unit/test_usage_recorder.py`（15 个用例）和 `tests/integration/test_usage.py`（10 个用例）。全部 181 个测试通过，用量相关测试连跑 3 次都稳定；ruff 和 mypy strict（app 和 tests）都干净。另外用脚本在测试库上跑了真实 lifespan，确认关闭时会把队列写完。
- **未完成**：无。Makefile 的 `rotate-credentials` 和 `gen-key` 按原计划放在任务 11。
- **下一步**：任务 9，对话图。调用时要传 `config={"configurable": {"thread_id": str(conversation.id)}, "metadata": {"user_id": str(user.id)}}`，用量记录就能拿到这两个 id。
- **踩坑**：
  - P0 里每个用户都是自己个人租户的 owner，而 `get_current_tenant` 按“owner 身份加个人租户”查找，所以通过 HTTP 走不到 403 这条路径。如果把角色降成 member，接口会直接返回 500（找不到个人租户）。目前的测试是直接调用 `require_tenant_manager`。做组织租户时，要改 `get_current_tenant` 的查找方式。
  - 用系统代理或设置了 `no_proxy` 时，langchain-openai 会打印一条“injected a custom httpx transport”警告。**这是误报**：它在检查我们是否自带 client 之前就打印了（`langchain_openai/chat_models/base.py:1496`），实际用的仍然是我们防护过的 client，已有测试覆盖。
  - 测试里 monkeypatch 了 `get_providers_config` 后，不要在测试函数体里调 `llm.reset_caches()`，因为这时它已被替换成普通函数，没有 `cache_clear`。应该用 autouse fixture，在 monkeypatch 还原之后再清理。

---

## 2026-09-28 · P0 任务 8 进行中（第 4 步完成，补记）

- **说明**：上一会话写完第 4 步后没来得及写交接记录，本条是新会话按代码实际状态补记的。
- **做了什么**：
  - `app/credentials/service.py`：连接的增删改查（`create_connection` / `update_connection` / `delete_connection`、`key_hint`），保存时用 `validate_base_url` 检查 URL；`verify_connection`；路由覆盖的 `list_route_overrides` / `put_route` / `delete_route`、`known_tasks`。
  - `app/api/providers.py`：`/provider-presets`、`/tenant/connections`（CRUD 与 `/{id}/test`）、`/tenant/routes`（GET、PUT、DELETE `/{section}/{task}`）。除 presets 外都要求 owner/admin（`require_tenant_manager`）。
  - `app/credentials/rotate.py`：`rotate_credentials`，以及命令行 `python -m app.credentials.rotate`。Makefile 入口放到任务 11。
  - `tests/integration/test_model_settings_api.py` 共 14 个用例。全部 156 个测试通过，ruff 和 mypy strict 都干净（本会话复核过）。
- **下一步**：第 5 步 llm_usage，方案待用户确认。
- **踩坑（本会话发现）**：因为我们显式传了 `base_url` 和 `http_async_client`，ChatOpenAI **不会自动开启 `stream_usage`**（`langchain_openai/chat_models/base.py:1431-1450`），流式调用拿不到 token 数。第 5 步要显式处理。

---

## 2026-09-28 · P0 任务 8 进行中（第 3 步完成）

- **做了什么**：
  - YAML 改为 `presets`（kind、base_url、label、推荐模型）加默认路由，已经不含任何 key。
  - `config.py` 改写：新增 `PresetSpec`、`ConnectionSpec`、`TenantProviderContext`、`ResolvedModel`、`route_for`、`resolve_route(config, ctx, section, task)`、`check_embedding_route`。
  - `errors.py` 新增 `NoModelConfiguredError`，带 `code` 字段（`no_llm_configured` / `no_embedding_configured`）。
  - `cache.py` 实现 `TTLCache`。
  - `tenant.py` 实现 `load_provider_context`：解密 key；已停用或解密失败的连接直接跳过；version 由各行的 updated_at 算指纹。
  - `llm.py` 改写：`build_chat_model` 注入防护过的 httpx2 client，显式传 base_url；anthropic 改用 `GuardedChatAnthropic`；`get_llm`、`get_structured_llm`、`get_chat_model`、`get_chat_models` 都改成 `(ctx, task)` 参数，缓存键为 `(tenant, task, version)`。
  - `embedding.py` 同样改成 ctx 版本。
  - lifespan 启动时不再校验路由，改为调用 `get_providers_config()`，只检查 YAML 结构。
  - 新迁移 `fe27d411cdcc`：`provider_connections.base_url` 改为 NOT NULL。
  - 新增 `app/db/schema_filter.py`，让 Alembic 忽略 LangGraph 的表；测试库现在也会建 checkpoint 表。
  - 共 131 个测试全部通过。
- **下一步**：第 4 步是连接和路由的 CRUD 接口，外加 `/provider-presets`、`/test` 和 `make rotate-credentials`；第 5 步是 llm_usage。
- **踩坑**：**Alembic autogenerate 差点生成 DROP LangGraph checkpoint 表的迁移**（会删掉所有对话历史）。已经用 `include_object` 过滤，并加了回归测试 `test_autogenerate_never_drops_langgraph_tables`。以后每次 autogenerate 后都要审一遍生成的迁移文件。

---

## 2026-09-28 · P0 任务 8 进行中（第 1–2 步完成）

- **做了什么**：
  - 第 1 步：`app/credentials/crypto.py` 实现了 `Keyring`（encrypt、decrypt、needs_rotation）、`parse_keyring`、`get_keyring`、`connection_aad`、`generate_key_entry`，以及命令行 `python -m app.credentials.crypto gen-key`。settings 新增 `credentials_encryption_keys` 和 `provider_allow_private_networks`；lifespan 启动时调 `get_keyring()`，没有主密钥就拒绝启动（放在 lifespan 而不是 Settings 校验里，这样迁移命令不需要密钥）。conftest 里设置了测试专用的密钥。
  - 第 2 步：`app/providers/net_guard.py` 实现了 `is_forbidden_ip`（专门处理了 IPv4-mapped 和 NAT64）、`resolve`（测试可替换）、`validate_base_url`、`GuardedNetworkBackend`、`make_async_http_client`（替换连接池的 `_network_backend`；不跟随重定向；trust_env=False）、`make_blocked_sync_client`。`app/providers/clients.py` 实现了 `GuardedChatAnthropic`，覆盖 `_async_client`，同步调用直接抛错。
  - 新增 `tests/unit/test_crypto.py` 和 `tests/unit/test_net_guard.py`。
- **未完成**：第 3–5 步：YAML 改为“预设 + 默认路由”并加上 TenantProviderContext 和缓存；连接和路由的 CRUD 以及 /test；llm_usage。
- **下一步**：第 3 步。`build_chat_model` 需要：对 openai 和 deepseek 传 `http_async_client=make_async_http_client(...)` 和 `http_client=make_blocked_sync_client()`；anthropic 改用 `GuardedChatAnthropic(...).with_http_client(...)`；**base_url 必须显式传入**，否则 SDK 会去读 OPENAI_BASE_URL / ANTHROPIC_BASE_URL 环境变量。
- **踩坑**：
  - **openai 3.19 和 anthropic 1.8 这两个 SDK 已经从 httpx 换成了 `httpx2` / `httpcore2`（API 完全相同的分支），并会对 http_client 做 isinstance 检查，传原版 httpx 的 client 会被拒收**。所以防护代码必须基于 httpx2，已加为显式依赖，也有测试 `test_sdks_accept_our_http_client_type` 覆盖。
  - Python 的 `ipaddress` 把 NAT64 地址（64:ff9b::/96）判为 is_global=True，即使它里面嵌的是 127.0.0.1。
  - ruff 的 ASYNC109 规则在实现 httpcore 接口时属于误报，已加带原因的 noqa。

---

## 2026-09-28 · P0 任务 7（鉴权）

- **做了什么**：
  - `app/auth/security.py`：`hash_password`、`verify_password`（返回 `(ok, new_hash)`，参数升级后会给出新哈希）、`burn_verify_time`、`create_access_token`、`decode_access_token`（限定算法为 HS256，要求 sub、exp、iat 三个声明，并检查 type 为 access）。
  - `app/auth/service.py`：`register_user`（同一事务里建 user、个人 tenant 和 owner 成员关系；邮箱是否重复以唯一索引为准）、`authenticate`、`get_personal_tenant`、`normalize_email`。
  - `app/api/auth.py`：register、login、token、logout、me 五个接口。
  - `app/deps.py`：`AUTH_COOKIE`、`get_current_user`（先看 Bearer，再看 cookie）、`get_current_tenant`，以及 `SessionDep`、`SettingsDep`、`CurrentUser`、`CurrentTenant` 几个类型别名。
  - settings：prod 下 JWT 密钥至少 32 字节；新增 `cookie_secure` 属性。
  - 新增 `tests/unit/test_security.py` 和 `tests/integration/test_auth_api.py`，conftest 里加了 `client` fixture，并设置了测试用的 JWT_SECRET。共 63 个测试全部通过，重复执行也稳定；ruff 和 mypy strict 都干净。
  - 用真实 uvicorn 和 curl 走了一遍完整流程：readyz、注册、cookie、me（cookie 和 Bearer 两种方式）、登出。ADR 0003 补了实现细节和 CSRF 的分析。
- **未完成**：无。
- **下一步**：任务 8（最大的一项），建议按这个顺序拆开做：
  1. `app/credentials/crypto.py`（AES-GCM，AAD 用 `tenant_id:connection_id`，密钥 id 加轮换）和 `make gen-key`；
  2. `app/providers/net_guard.py`（保存时检查 URL；连接时用自定义 `httpcore.AsyncNetworkBackend` 检查 IP；ChatAnthropic 子类）；
  3. YAML 改为“预设 + 默认路由”，`config.py` 和 `llm.py` 改成用 `TenantProviderContext`，缓存改成 LRU + TTL，键为 `(tenant_id, task, version)`，删掉启动时的 `validate_llm_routes`；
  4. 连接和路由的 CRUD 接口，以及 `/test`；
  5. `llm_usage` 回调和用量查询接口。
- **踩坑**：
  - conftest 设置了 `JWT_SECRET` 环境变量，依赖默认值的 settings 测试要显式传参。
  - 删除用户时只会级联删掉 tenant_members，**个人租户会变成孤儿**。以后做“注销账号”时要同时删除个人租户（P1 前补上）。
  - `pkill -f` 又杀掉了执行它的 shell，清理命令要分开跑。

---

## 2026-09-28 · P0 任务 6（数据库）

- **做了什么**：
  - compose 加了 postgres（`pgvector/pgvector:pg16`，实际版本 16.15，pgvector 0.8.6），宿主机端口默认 5433；init 脚本会建 `lingo_test` 库。
  - `app/db/`：
    - `base.py`：命名约定、`TimestampMixin`。
    - `models.py`：Tenant、User、TenantMember、Conversation、ProviderConnection、TenantModelRoute、LLMUsage。
    - `session.py`：`create_engine`、`create_sessionmaker`。
    - `urls.py`：`to_psycopg_conninfo`。
    - `migrate.py`：`alembic_config`、`setup_checkpointer`、`main`。
    - Alembic async 的 `env.py`：支持通过 `config.attributes` 注入 URL 或现成的连接。
    - 首个迁移 `20260928_0849934f390e_initial_schema.py`，包含 vector 扩展。
  - `app/api/health.py` 新增 `/readyz`；`app/deps.py` 新增 `get_session`；`main.py` 新增 `init_state`，lifespan 负责创建和释放 engine。
  - `tests/conftest.py`：`db_engine`（session 级，每次先降级到 base 再升级到 head）、`db_session`（每个测试结束后 TRUNCATE），以及只允许 `_test` 库的安全阀。
  - 新增测试：迁移往返、模型与迁移是否一致、唯一约束、CHECK 约束、级联删除、删除用户后用量记录保留（user_id 置空）、readyz 的 200 和 503。共 45 个测试全部通过，重复执行也稳定；ruff 和 mypy strict 都干净。
  - `python -m app.db.migrate` 已在开发库上跑过，8 张业务表和 4 张 checkpoint 表都已创建。
- **未完成**：`/readyz` 只用 ASGI 测试验证过，没用 uvicorn 实际起服务验证，因为 lifespan 里的 `validate_llm_routes()` 在没有厂商 key 的环境变量时会失败，这个过渡状态要到任务 8 才解决。Makefile 放在任务 11。
- **下一步**：任务 7（鉴权）：`uv add` pyjwt 和 `pwdlib[argon2]`；写 `app/auth/security.py`（`hash_password`、`verify_password`、`create_token`、`decode_token`）、`app/auth/service.py`（`register_user` 在同一个事务里建 user、个人 tenant 和 owner 成员关系；`authenticate`）、`app/api/auth.py`（register、login、logout、me，cookie 加 Bearer）；`deps.py` 加 `get_current_user` 和 `get_current_tenant`。
- **踩坑**：
  - 本机 5432 端口被别的项目的容器 `docker-db-1` 占着，不要去动它，本项目用 5433。
  - Alembic 的 post_write_hooks 必须先跑 format 再跑 check，否则会误报 E501。
  - 在已经运行的事件循环里跑 Alembic，要用 `conn.run_sync(run_alembic, ...)` 并通过 `config.attributes["connection"]` 传入连接，不能调用 `asyncio.run`。
  - `alembic init` 不支持 `-q` 参数。

---

## 2026-09-28 · P0 任务 5（可选 OTel tracing）

- **做了什么**：
  - `app/settings.py` 新增 `otel_tracing_enabled`（默认 False）、`otel_exporter_otlp_endpoint`、`otel_service_name`。
  - `app/observability.py`：`setup_tracing(settings, span_processor=None)` 和 `shutdown_tracing(provider)`。TracerProvider 显式传给 LangChainInstrumentor，不修改 OTel 的全局 provider。lifespan 里接好了初始化和关闭。
  - `docker-compose.yml` 首次创建，目前只有 phoenix 服务（profile `observability`，镜像 `version-20.16.0`，mem_limit 1g）。
  - `tests/unit/test_observability.py`：用内存 exporter 验证 LangGraph 根图、节点和模型调用都会生成 span、带上 metadata、属于同一条 trace。
  - 手动端到端验证：真实 OTLP 导出到 Phoenix，用 REST API 能查回三个 span。测试共 36 个全部通过；ruff 和 mypy 都干净。
- **未完成**：Makefile 还没写（任务 11），目前启动 Phoenix 的命令是 `docker compose --profile observability up -d`。
- **下一步**：任务 6：在 compose 里加 postgres（pgvector/pgvector:pg16）；`uv add` sqlalchemy[asyncio]、alembic、psycopg[binary,pool]；写 `app/db/{base,session,models}.py` 和 Alembic async 迁移，建 users、tenants、tenant_members、conversations、provider_connections、tenant_model_routes、llm_usage 七张表；实现 `/readyz`。
- **踩坑**：
  - `docker manifest inspect` 在这台机器上总是失败，要确认镜像 tag 是否存在，直接 `docker pull`。Phoenix 的 tag 格式是 `version-X.Y.Z`，镜像约 1.5GB。
  - 在 backend 目录外跑脚本时需要 `PYTHONPATH=.`。
  - OpenInference 的实现方式是包装 `BaseCallbackManager.__init__`，是全局 monkeypatch。测试结束后必须调用 `shutdown_tracing` 撤销，否则会影响后面的测试。

---

## 2026-09-28 · 设计变更：可观测性去 LangSmith；任务 4 完成

- **做了什么**：
  - 用户确认：语音 key 同样由租户配置；不用 LangSmith（它是闭源 SaaS，自托管需要企业版授权），采用 A+B 方案。
  - 写了 ADR 0005：A 是自建 `llm_usage` 用量表，租户可见；B 是可选的 OTel tracing，默认关闭，dev 用本地 Phoenix。
  - ADR 0004 改为“已采纳”。ADR 0002 被取代的部分用删除线标出；ADR 0001 也加了指向新 ADR 的说明。
  - 同步了 PLAN.md、CLAUDE.md、README 和 P0 计划 §14。`.env.example` 重写：只留部署方配置，新增 CREDENTIALS_ENCRYPTION_KEYS、PROVIDER_ALLOW_PRIVATE_NETWORKS、OTEL_*，删除所有厂商 key 和 LANGSMITH_*。
  - conftest 中强制关闭 OTel 和 LangSmith 的上报。
- **未完成**：`config/providers.*.yaml` 仍然带 `api_key_env`，`app/providers/config.py` 仍然从环境变量解析 key，`main.py` 仍在启动时调 `validate_llm_routes()`。这些都在任务 8 统一改。现在服务在没有厂商 key 的环境变量时启动不了，这是预期中的过渡状态。
- **下一步**：任务 5：`uv add` openinference-instrumentation-langchain、opentelemetry-sdk、opentelemetry-exporter-otlp-proto-http；写 `app/observability.py` 的 `setup_tracing(settings)`；compose 里加 phoenix 服务（profile `observability`）；实测 LangGraph 节点能不能产生 span。
- **踩坑**：已核实的许可证：openinference-instrumentation-langchain 0.1.76、opentelemetry-sdk 1.45 和 OTLP HTTP 导出器 1.45 都是 Apache-2.0。Phoenix 服务端是 ELv2，只作为独立容器按需运行。

---

## 2026-09-28 · 设计变更：多租户凭据

- **做了什么**：用户决定：模型厂商的 key 不放在配置里，由租户自己配置。具体是个人租户（预留组织）、只用租户自己的 key、租户可以自定义 base_url、模型和路由，在 P0 做完最小闭环。据此写了 ADR 0004（状态：提议），修订了 `docs/plans/P0-skeleton.md` 的 §11 和 §13，同步了 PLAN.md、CLAUDE.md 和看板（任务重新编号为 1–13）。原来的 3b“真实 key 冒烟”已删除。
- **未完成**：ADR 0004 等用户确认。代码还没改：`app/providers/config.py` 仍有 `api_key_env`，`main.py` 仍在启动时调 `validate_llm_routes()`，`.env.example` 里还有厂商 key。这些都在任务 4 和任务 8 里改。
- **下一步**：用户确认 ADR 0004 后，执行任务 4：ADR 0004 改为“已采纳”，改写 ADR 0002 被取代的部分，YAML 改为“预设 + 默认路由”，从 `.env.example` 删除厂商 key。
- **踩坑**：ChatAnthropic 没有 `http_async_client` 字段，它在私有 cached_property `_async_client` 里自己构造 httpx client；要做 SSRF 防护只能写子类覆盖它。ChatOpenAI 和 ChatDeepSeek 可以直接传 `http_async_client`。httpcore 的 `AsyncConnectionPool` 支持 `network_backend` 参数，可以用它在连接时检查 IP。

---

## 2026-09-28 · P0 任务 3（provider 层）

- **做了什么**：
  - `app/providers/config.py`：`ProvidersConfig`、`RouteSpec`（路由可写成字符串、列表或对象）、`load_providers_config`、`resolve_route`（跳过没有 key 的模型并打 warning；整条链都不可用时抛 `ProviderConfigError`）。
  - `app/providers/llm.py`：`build_chat_model`、`get_chat_models`（有缓存）、`get_llm`、`get_structured_llm`（先给每个模型绑定 schema，再串降级链）、`get_chat_model`、`validate_llm_routes`、`reset_caches`。
  - `app/providers/embedding.py`：`get_embeddings`，只允许单模型、不做降级链。
  - `config/providers.{dev,prod}.yaml`；`.env.example` 新增 APP_ENV、PROVIDERS_CONFIG、DASHSCOPE_API_KEY。
  - `main.py` 的 lifespan 在启动时校验所有 LLM 路由。ADR 0002 补了两条：embedding 不做降级链、embedding 延迟校验。
  - 测试共 34 个，全部通过；ruff 和 mypy strict 都干净。
- **未完成**：3b 真实 key 冒烟测试（需要 `.env`）；YAML 里的模型名（`deepseek-chat`、`claude-sonnet-5`、`gpt-5-mini`、`qwen-plus`）还没用真实 API 核对过。
- **下一步**：用户建好 `.env` 后跑冒烟测试：`cd backend && uv run python -c "import asyncio; from app.providers.llm import get_llm; print(asyncio.run(get_llm('chat').ainvoke('Say hi in 3 words')).content)"`。之后做任务 4（`app/observability.py`）。
- **踩坑**：
  - langchain-core 1.6 在每个流末尾都会多发一个 content 为空的 chunk。任务 7 的 SSE 转发必须过滤掉空 chunk。
  - `with_structured_output` 的类型注解写的是返回 `dict | BaseModel`，所以用 `cast` 标注成具体类型，代码注释里写了原因。
  - 现在服务启动时要求至少有一个 LLM key，没有 `.env` 时 uvicorn 起不来（这是 ADR 0002 规定的行为）。用 ASGITransport 跑测试不会触发 lifespan，不受影响。
  - 用 heredoc 写的 .py 文件不会触发 PostToolUse 的 ruff format 钩子，要手动跑 `ruff format`。

---

## 2026-09-28 · P0 任务 1–2

- **做了什么**：任务 1：写了 ADR 0002（provider 层）和 0003（鉴权与流式），同步修改了 PLAN.md 和 CLAUDE.md 里的配置文件名。任务 2：完成 backend 脚手架，包括 `backend/pyproject.toml`（uv；ruff、mypy strict、pytest 的配置）、`app/settings.py`（`Settings`、`get_settings`；APP_ENV=prod 时如果 JWT_SECRET 还是默认值就拒绝启动；PROVIDERS_CONFIG 用相对路径时按仓库根目录解析）、`app/main.py`（`create_app`、lifespan）、`app/api/health.py`（`/healthz`），另有 6 个测试。ruff、mypy、pytest 全部通过，用 uvicorn 实际起服务、curl `/healthz` 也验证过。
- **未完成**：任务 3 provider 层还没开始写。
- **下一步**：`uv add` langchain、langchain-openai、langchain-anthropic、langchain-deepseek；写 `app/providers/{config,llm,embedding,errors}.py` 和 `config/providers.{dev,prod}.yaml`，再按计划 §10 写单测。
- **踩坑**：`pkill -f` 的匹配模式会连同执行它的 shell 一起匹配上，导致退出码是 144，这个退出码可以忽略。依赖只在用到它的那个任务里 `uv add`，不提前一次性装齐。

---

## 2026-09-28 · P0 详细实施计划

- **做了什么**：写出 `docs/plans/P0-skeleton.md`（依赖版本、目录结构、provider 配置格式与接口、DB/鉴权/SSE 设计、compose、测试与 CI、11 个任务的顺序与验证方式）；PROGRESS.md 的 P0 拆成 11 个任务。依赖版本是当天从 PyPI / npm 查的。
- **未完成**：计划 §12 的 Q1–Q6 等用户确认；还没有写代码。
- **下一步**：~~用户确认后开始任务 1~~ → 已确认（Q1–Q6 全部按推荐），任务 1 完成：ADR 0002（provider 层）、0003（鉴权与流式）已写，PLAN.md / CLAUDE.md 的配置文件名同步为 providers.{dev,prod}.yaml。接下来做任务 2（backend 脚手架）。
- **踩坑**：①`RunnableWithFallbacks.__getattr__` 会把 `bind_tools` / `with_structured_output` 转发到每个 fallback，但要靠 `typing.get_type_hints` 解析返回类型，对部分模型会抛 NameError → provider 层要显式包装。②fallback 流式只在第一个 chunk 前切换模型。③npm 最新 TypeScript 是 7.0，先跟随 create-next-app 的版本。④`langgraph-checkpoint-postgres` 只支持 psycopg3，全项目统一用这个驱动。

---

## 2026-09-28 · 项目立项

- **做了什么**：确认整体方案（docs/PLAN.md）；初始化仓库；建立会话记忆协议（CLAUDE.md、PROGRESS.md、本文件、ADR 0001）。
- **未完成**：还没有写业务代码。
- **下一步**：输出 P0 详细实施计划（目录结构、依赖版本、provider 接口定义、compose 服务配置），确认后开始实现。
- **踩坑**：无。
