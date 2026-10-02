# P2 自适应引擎完整版 + 写作 + 阅读 + 语法图谱 · 详细实施计划

> 状态：**已确认**（2026-10-02）。D1–D4 与 Q5–Q13 见 §10，按 §9 的顺序执行。
> 上位设计见 `docs/PLAN.md` 第二·五节、第四节 P2。本文件只写 P2 范围内“怎么做”，超出 P2 的只留接口。
> 相关 ADR：已有 0010 学习者模型、0012 规则与证据、0013 工具与公示、0014 AI 用量公示、0015 私教工具与确认卡、0016 对话式建议；P2 新增 0021–0025（§9 任务 30）。

## 0. P2 的完成定义（Demo 脚本）

在 P1 Demo 的基础上（已做入学测、有一些对话里的错误证据）：

1. **练习**：看板“今天”或学习者模型页点“练一组” → 进入 `/practice`，约 10 题。题目覆盖薄弱语法点，中间夹着已掌握的点（交错），题型轮换：选择、填空、找错改错、句型转换、中译英、改写自己说错过的原句。每题答完马上看到“为什么错、正确用法对比”。整组结束后看到这组覆盖了哪些语法点、掌握度怎么变了。
2. **出题质量**：每道 LLM 生成的题都由 critic 独立做一遍，答案不唯一、答案错、难度不符、和语法点不符的题不会给学习者；学习者也能对单题点“这题有问题”。
3. **“学会”**：学习者模型页的语法点显示“已掌握”的条件进度（几种题型答对、跨了几天、最近对话里是否又错）；已掌握的语法点到期会出现在复习里（语法点接入 FSRS）。
4. **写作**：`/writing` 选一个按等级出的题目（或自己写），提交后看到逐句修改、每处错误对应的语法点、四个维度的评语；错误进入学习者模型，不会的词进生词本。对话里贴一段作文说“帮我改改”，Supervisor 路由给写作 coach，给出同样的批改并链到写作记录。
5. **阅读**：`/reading` 看到内置来源（NASA 新闻稿、Global Voices）和自己订阅的 RSS 文章，按自己的等级改写过（i+1），原文链接到出处。阅读时悬停查词、点词收进生词本，今天到期的词在文中高亮。读完做 3–5 道理解题，结果计入阅读能力估计。订阅的源由后台定时抓取。
6. **诊断**：学习者模型页有“私教的诊断”：带证据引用的根因假设（例如“虚拟语气错 6 次，其中 4 次是 would have done 形式，根因可能是完成时”），点证据能跳到原句；诊断结果会抬高相关前置语法点的出题优先级。
7. **每日计划**：每天第一次打开看板，“今天”的私教给出今天的计划（复习 N 个词、学 M 个新词、一组练习、一篇阅读），学习者在确认卡上确认或调整；看板上能勾掉完成项。
8. 所有新的模型调用都在 `features.yaml` 登记、入口挂 `AiBadge`、在 `docs/agent-tools.md` 公示；后台调用有每日上限，学习者能关掉。
9. `make test`、`make lint`、`make e2e` 全绿；GitHub Actions 全绿。

**P2 不做**：语音（P3）、评估集的 CI 回归和成本看板（P4，P2 只为 critic / 批改建最小评估集，见 Q13）、拼写 / 听音背词题型（P3 和语音一起）、文档 RAG。

---

## 1. 范围与子阶段

| 子阶段 | 内容 | 依赖 | 对应 Demo |
|---|---|---|---|
| **P2a** 练习引擎 | 题型与数据表、选题规划（优先级 + 交错 + 85% 规则）、出题子图（生成 → critic → 重生成）、批改、语法点接入 FSRS、“学会”判定、`/practice` 页 | P1 的 KC、BKT、Elo | 1、2、3 |
| **P2b** Supervisor + 写作 | 主图加 Supervisor 路由（D4）、写作 coach、`/writing` 页、写作证据回写 | P2a 的批改结构 | 4 |
| **P2c** 阅读 + 定时任务 | 定时任务框架、RSS 抓取（NASA + Global Voices + 自加，D3）、分级改写、阅读页、理解题、到期词高亮、阅读 coach；后台预生成 AI 例句（P2 看板里的积压项） | P2b 的 Supervisor（阅读 coach） | 5 |
| **P2d** 语法图谱 + 诊断 | `kc_edges`（Postgres，D2）、易混关系起草与审核、图谱检索、诊断 Agent、诊断页面、诊断反馈到选题 | P2a 的选题；P2c 的定时任务（每周诊断） | 6 |
| **P2e** 每日计划 | 计划算法、“今天”对话里提出计划、确认卡、看板勾选 | 前面全部 | 7 |

顺序按 D1：先补完“证据 → 掌握度 → 出题 → 作答 → 证据”的闭环。

---

## 2. 新增依赖（开工前逐个核实版本、许可和内存）

| 包 | 用途 | 备注 |
|---|---|---|
| `apscheduler` 3.x | 进程内定时任务（P2c） | 纯 Python，MIT，无外部服务；2026-06-28 的 3.11.3 是最新稳定版（4.0 仍是 alpha，不用）；只跑一个后端实例时可用（ADR 0025）。备选：照 `ReflectionWorker` 自己写 asyncio 循环 |
| `feedparser` 6.x | 解析 RSS / Atom（P2c） | 纯 Python，BSD-2-Clause；2026-07-30 的 6.0.14，依赖只有 `feedparser-sgmllib` |
| 正文抽取（如 `trafilatura`） | 自加 RSS 只给摘要时抓正文（P2c） | 依赖 lxml；两个内置来源的 RSS 都带全文，P2 先不引入，任务 41 实测内存后再定（ADR 0024） |

语法图谱不引入 Neo4j（D2），compose 里的 `neo4j` profile 在任务 30 一并删除。

---

## 3. 练习引擎（P2a，ADR 0021）

### 3.1 题型（Q5）

| format | 证据类型 | 判对方式 | 说明 |
|---|---|---|---|
| `choice4` | recognition | 代码比对 | 复用入学测格式；入学测 90 题可做无模型时的兜底题库 |
| `cloze` | recognition | 代码比对（规范化 + 可接受答案列表） | 句中挖空，给词根提示 |
| `find_fix` | recognition + production | 找错位置代码比对；改法代码比对，不在列表里再交给批改模型 | 找茬 |
| `transform` | production | 批改模型 | 句型转换（主动 → 被动、直接 → 间接引语……） |
| `translate` | production | 批改模型 | 中译英，限定目标语法点 |
| `rewrite_own` | production | 批改模型 | 取学习者 `kc_evidence.original` 里自己说错过的句子让他改（只用最近 30 天、来自对话的证据） |

每种题型在 `rules.yaml` 的 `elo.guess_by_format` 登记猜中率。

### 3.2 数据表

- `exercise_sets`：一组练习（user_id、kc_plan JSONB、status `generating/ready/in_progress/done/failed`、来源 `dashboard/learner/card/plan`、创建与完成时间）。
- `exercises`：user_id、set_id、kc_id（主 KC）、format、content JSONB（题干、选项、提示）、answer JSONB（标准答案、可接受答案、讲解）、difficulty（rubric 先验，同入学测）、critic JSONB（判定、理由、独立作答）、status `ok/rejected/reported`、生成用的路由与模型。
- `attempts`：user_id、exercise_id、response JSONB、correct、latency_ms、feedback JSONB、created_at。
- `kc_evidence`：`source` 加 `exercise`、`writing`、`reading`；新增可空列 `format`、`attempt_id`（迁移要改 check 约束）。
- `kc_mastery`：新增 `formats_passed`（答对过的题型集合）、`days_passed`、FSRS 状态列（语法点复习，§3.6）。

### 3.3 选题规划（纯算法，单测）

- **优先级** = 薄弱度（1 − p_mastery）× 重要度（KC 等级与学习者等级的距离、最近 30 天错误次数）× 到期（FSRS 到期的已掌握 KC 加权）× 诊断加成（P2d 之后）。
- **交错**：一组 10 题里约 70% 来自薄弱 KC，30% 来自已掌握或到期 KC；同一 KC 不连续出现，同一题型不连续超过两题。
- **85% 规则**：用学习者的语法 Elo 能力值和题目 rubric 难度算预计正确率，目标 0.80–0.85；选题时给生成器“目标难度”，作答后 Elo 校准题目难度（同入学测）。
- 参数全部放 `rules.yaml`（ADR 0012 的做法），改参数换版本号。

### 3.4 出题子图（LangGraph，mock LLM 集成测试）

`plan → generate → critic → (重生成，最多 2 轮) → persist`

- `generate`（task `exercise_generate`）：一次结构化调用出一组题，输入：KC 说明与常见错误、目标难度、题型、学习者兴趣和职业（记忆里的事实，个性化语境）、`rewrite_own` 的原句。
- `critic`（task `exercise_critic`，可路由到不同模型）：**不看标准答案**先独立作答，再对照：答案是否唯一且正确、是否真的考这个 KC、难度是否在目标附近、是否有文化或事实错误。不通过的题带理由回到 `generate` 重写；两轮仍不通过就丢弃，不足的用题库兜底。
- 生成时机（Q7）：开始一组时现生成（等待时显示 hop 猫和进度），做完一组后后台预生成下一组。
- 学习者点“这题有问题”：题目标为 `reported`，不计证据，记入评估集候选（Q13）。
- **落地记录（任务 33，2026-10-02）**：Q33a–g 已确认，细节写在 ADR 0021 §3、§4。代码：`adaptive/exercise/inputs.py`（选题输入）、`drafts.py`（扁平 schema、组装、`judge`）、`messages.py`、`bank.py`（题库补位四档）、`service.py`（存库、`how_made`）、`worker.py`（`PracticeWorker`）、`agents/exercise_graph.py`；`rules.yaml` `2026-10-02.3`；迁移 `9f45cf7f00b8`（`exercise_sets.rules_version`）。没入学测的新学习者按 A2，A2 窗口多数语法点先验 p ≥ 0.4，所以第一组几乎全是产出题，实测时留意；入学测和重测提醒另立任务 50。

### 3.5 批改

- 代码能判的直接判；开放题交给 `exercise_grade`（结构化）：`correct`、讲解、对比、以及答案里**别的**语法错误（像 reflect 一样打到其他 KC，严重度规则同对话）。
- 批改模型只判断“这次答案对不对”，掌握度仍由 BKT 按证据更新（不违反“LLM 不打掌握度”）。
- 每次作答写 `attempts` 和 `kc_evidence`（source `exercise`，format 按题型），然后 `mastery.refresh`。

### 3.6 语法点接入 FSRS 与“学会”判定

- KC 第一次达到“学会”时创建 FSRS 卡（复用 `fsrs` 库），之后到期就进入选题的“到期”部分；练习里答对 / 答错映射到 Good / Again。
- “学会”= p_mastery ≥ mastered 阈值 **且** ≥ 3 种题型答对 **且** 跨 ≥ 2 天 **且** 最近 N 轮对话里没有同 KC 的计入错误（阈值放 `rules.yaml`）。学习者模型页显示这四项的进度。

### 3.7 页面

- `/practice`：一题一屏（手机友好），键盘快捷键同入学测；答完显示讲解；结束页（done 猫）列出本组 KC 与掌握度变化，“再来一组”。
- 入口：看板“今天”的快捷回复与卡片、学习者模型页每个 KC 的“练一组”、私教卡片 `suggest_practice` 增加“做题 / 对话练习”两个去处。
- `features.yaml`：`practice_set`（generate + critic，时机 now；预生成下一组 background）、`practice_grade`（每题，now）。

---

## 4. Supervisor 与写作（P2b，ADR 0023）

### 4.1 Supervisor（D4，Q9）

- 主图改为 `START → load_context → supervisor → {tutor, grammar_coach, writing_coach, reading_coach} → …`；各 coach 是子图，有自己的提示词和工具集，共享 `ChatContext` 和 checkpoint 线程。
- 路由先看确定的信号，不调模型：会话的 `focus_kc_id` → grammar_coach，会话 `purpose`（planning / daily）→ tutor，写作页、阅读页发起的会话 → 对应 coach。只有自由对话才走一次轻量结构化路由（task `route`），判断是否要转给写作 / 阅读 / 语法 coach；分类失败就留在 tutor。
- 现有的 practice（`focus_kc_id`）分支、planning / daily 分支从 `api/chat.py::_reply` 挪进路由，`_reply` 只负责组装 context。
- 活动公示：路由结果作为一个 step（“交给了写作 coach”）出现在“私教做了什么”。

### 4.2 写作

- 表 `writing_submissions`：user_id、prompt、text、corrections JSONB（逐句：原句、改后、错误列表〔KC、error_type、severity、讲解〕）、scores JSONB（任务完成、连贯、词汇、语法四维，带一句理由，只展示，不进掌握度）、conversation_id（从对话来时）、created_at。
- 批改（task `writing_review`，结构化）：KC id 必须在清单里，不在的丢弃；错误证据 source `writing`、evidence `production`；生词进生词本（复用 reflect 的 vocab_candidates 规则）。
- 题目：按等级和画像里的目标（考试、兴趣）出，`writing_prompt` 调用可选（也可自己写，不花 token）。
- `/writing`：写作框（字数统计）、提交、逐句对照视图、历史记录；对话里贴作文时 writing_coach 调同一个服务，回复里给卡片链到这条记录。
- `features.yaml`：`writing_review`、`writing_prompt`。

---

## 5. 阅读与定时任务（P2c，ADR 0024、0025）

### 5.1 定时任务

- ADR 0025：进程内 `AsyncIOScheduler`，任务定义在代码里，启动时注册；部署约定只跑一个后端实例（compose 已是如此）；任务幂等，重启后按数据库里的“上次运行”补跑。
- 任务：抓取 RSS（每 2 小时）、为订阅者的等级预改写新文章（受每日上限）、每周诊断（P2d）、每日计划预计算（P2e）、后台预生成 AI 例句（看板 P2 积压项，先看 Tatoeba 覆盖率再定范围）。
- **后台调用上限**（Q12）：租户级每日 token 上限（设置页可改），每个后台功能学习者可关；在 `features.yaml` 登记为 `timing: background`。

### 5.2 来源与存储（D3）

- 内置源（D3，2026-10-02 修订，见 ADR 0024）：NASA 新闻稿 RSS（美国政府作品，公有领域）、Global Voices RSS（CC BY 3.0，允许改写；标了 CC BY-NC-ND 的转载文章跳过）。两者 RSS 都带全文。原定的 VOA Learning English 所有 feed 自 2025 年 3–4 月起停更，不再内置。学习者可加自己的 RSS。
- 表：`feeds`（全局内置 + 用户自加，url、标题、上次抓取、etag）、`feed_subscriptions`（user、feed、topics）、`articles`（feed、url、标题、发布时间、原文正文、来源许可标记）、`article_versions`（article、目标 CEFR、改写正文、词表、理解题 JSONB、生成模型）、`reading_sessions`（user、article_version、开始 / 完成、点过的词、题目作答）。
- 抓来的全文只在部署方自己的数据库里，不进仓库（CLAUDE.md）；非公有领域来源的界面上始终显示出处和原文链接。

### 5.3 分级改写与阅读页

- `article_rewrite`（结构化）：目标等级 = 学习者等级的 i+1（半级以内），保留事实；输出改写正文、超纲词表（词库里查得到的才保留）、3–5 道理解题（choice4，带答案依据句）。理解题同样过 critic（复用 §3.4 的 critic，题型 `reading_choice`）。
- 改写结果按（租户、文章、等级）缓存：同一租户里同一篇文章同一等级只改写一次（用的是该租户的模型和 token，不跨租户共享，见 ADR 0024）。
- `/reading`：文章列表（来源、等级、话题），阅读器复用单词气泡（悬停查词、朗读、收词），到期词高亮，读完做理解题；理解题作答更新 `skill_estimates.reading`（Elo），涉及的语法点不计证据。
- reading_coach：对话里问“这篇文章里的 X 是什么意思 / 帮我总结”，带文章上下文回答。

---

## 6. 语法图谱与诊断（P2d，ADR 0022）

### 6.1 图谱（D2）

- 真相源仍是 `adaptive/kc/grammar.yaml`：已有 `prerequisites`，新增 `confusable_with`（同类易错，LLM 起草 → 用户审核，同任务 6 的做法）。
- 启动时（或 `make kc-sync`）同步到 `kc_edges`（from_kc、to_kc、kind `prerequisite/confusable`），用递归 CTE 查前置链（深度 ≤ 3）并直接 join 学习者的 `kc_mastery`、`kc_evidence`。查询封装在 `adaptive/graph.py`，以后要换图数据库只改这一层。
- GraphRAG 检索：给定薄弱 KC → 前置链 + 易混 KC → 各自掌握度、最近证据（原句 / 改正）→ 拼成诊断上下文。

### 6.2 诊断 Agent

- 触发：每周一次（定时任务）+ 一组练习结束后、有新证据时（每人每天最多一次）。
- `diagnose`（结构化）：输出 `root_causes[{hypothesis, kc_ids, evidence_ids, confidence, suggestion}]`；代码校验 evidence_ids 属于该学习者且对应 KC，引用不到证据的假设丢弃。
- 表 `diagnoses`（user、period、root_causes JSONB、生成时间、规则版本）；同时写一条事实记忆（学习者可在记忆页删除）。
- 学习者模型页新增“私教的诊断”区块（证据可点）；选题优先级对诊断指向的前置 KC 加成（§3.3）。
- `features.yaml`：`diagnosis`（background）。

---

## 7. 每日计划（P2e）

- 计划算法（纯函数）：按画像的每日分钟数分配：到期复习词数、新词数、一组练习（优先级最高的 KC）、一篇阅读（有订阅时）、可选写作；估时参数放 `rules.yaml`。
- 表 `daily_plans`（user、日期、items JSONB、status、确认时间）、完成情况由各模块的完成事件回填。
- “今天”对话里私教用新工具 `propose_daily_plan` 提出计划，走现有确认卡（proposed → applied / declined / undone，Q11）；学习者可在卡片上调数量。看板显示计划清单和完成勾。

---

## 8. 表汇总与迁移

新增：`exercise_sets`、`exercises`、`attempts`、`writing_submissions`、`feeds`、`feed_subscriptions`、`articles`、`article_versions`、`reading_sessions`、`kc_edges`、`diagnoses`、`daily_plans`、`scheduler_runs`（任务上次运行）。修改：`kc_evidence`（source 扩展、`format`、`attempt_id`）、`kc_mastery`（`formats_passed`、`days_passed`、FSRS 列）、`conversations.purpose`（加 writing / reading）。

- 每个子阶段一个或多个迁移，不一次建完；用户数据表都有 `user_id` FK 级联删除。
- 规则改动走 `rules.yaml` 版本号，已有掌握度按 ADR 0012 用到时重放。

---

## 9. 任务顺序

每项完成标准：测试通过、lint 干净、看板已更新；涉及模型调用的同步 `features.yaml`、`AiBadge`、`docs/agent-tools.md`。

| # | 任务 | 验证 |
|---|---|---|
| 30 | ADR 0021 练习引擎、0022 语法图谱存 Postgres（取代 PLAN 的 Neo4j）、0023 Supervisor 与 coach、0024 阅读来源与版权、0025 定时任务；PLAN 同步（技术栈、数据模型、P2 段）；删 compose 的 neo4j profile | 人工 review |
| **P2a** | | |
| 31 | 数据表与迁移（§3.2）+ 题型定义 + `rules.yaml` 新参数 | 迁移往返；单测 |
| 32 | 选题规划纯函数（优先级、交错、85% 规则）+ “学会”判定 + 语法点 FSRS | 单测 |
| 33 | 出题子图（generate → critic → 重生成 → 题库兜底）+ 后台预生成下一组 | mock LLM 图测试 |
| 34 | 批改服务（代码判 + `exercise_grade`）+ 作答 → 证据 → 掌握度 | 集成测试 |
| 35 | 练习接口 + `/practice` 页 + 入口（看板、学习者模型、私教卡片）+ 学习者模型页“学会”进度 | Vitest + E2E（假模型） |
| 36 | 最小评估集（Q13）：critic 能拒掉已知坏题、批改判对已知答案 | pytest |
| **P2b** | | |
| 37 | Supervisor 路由 + 现有分支迁入 + 路由活动公示 | 图测试 |
| 38 | 写作批改服务 + 表 + 证据回写 + writing_coach | 集成测试 |
| 39 | `/writing` 页 + 对话里的写作卡片 | Vitest + E2E |
| **P2c** | | |
| 40 | 定时任务框架 + 后台调用上限 + 设置页开关 | 单测 + 集成测试 |
| 41 | RSS 抓取（NASA + Global Voices + 自加）+ 文章表 | 本地 fixture feed 测试 |
| 42 | 分级改写 + 理解题（过 critic） | mock LLM 测试 |
| 43 | `/reading` 页 + 到期词高亮 + 理解题 → 阅读能力 + reading_coach | Vitest + E2E |
| 44 | 后台预生成 AI 例句（先看覆盖率再定范围） | 集成测试 |
| **P2d** | | |
| 45 | `confusable_with` 起草 → 用户审核；`kc_edges` 同步与图查询 | 单测 |
| 46 | 诊断 Agent + 表 + 记忆写入 + 选题加成 | 集成测试 |
| 47 | 学习者模型页“私教的诊断” | Vitest + E2E |
| **P2e** | | |
| 48 | 每日计划算法 + 表 + `propose_daily_plan` 工具 + 确认卡 + 看板清单 | 单测 + E2E |
| 49 | P2 Demo 实测 + README 更新 + Docker 重建 | 用户实测 |

---

## 10. 决定

**已确认（2026-10-02）**

- **D1 子阶段顺序**：先练习引擎，之后写作 → 阅读 → 图谱诊断 → 每日计划。
- **D2 语法图谱**：存 Postgres（`kc_edges` + 递归查询），不引入 Neo4j；查询封装一层，以后可换。
- **D3 阅读来源**：~~内置 VOA Learning English（公有领域）~~ 2026-10-02 修订：VOA Learning English 的 RSS 全部停在 2025 年 3–4 月，改为内置 NASA 新闻稿（公有领域）+ Global Voices（CC BY 3.0，跳过 NC-ND 转载）+ 学习者自加 RSS；全文只存在部署方数据库，界面显示出处和许可（ADR 0024）。
- **D4 Supervisor**：按 PLAN 原计划做 Supervisor 主图，路由到各 coach 子图。

**已确认（2026-10-02，Q5–Q13 全部按推荐）**

- **Q5 第一批题型**：§3.1 的六种全做（变式是“不死板”的关键，`rewrite_own` 是最个性化的一种）。
- **Q6 开放题判对**：批改模型只判对错 + 讲解，顺带标出答案里别的语法错误；部分正确按“目标 KC 判对、其他错误另记证据”。
- **Q7 出题时机**：开始一组时现生成（约 10–20 秒，显示 hop 猫和进度），做完后后台预生成下一组。
- **Q8 题目复用**：题目按学习者私有（带个人语境），不跨用户共享；入学测题库作为全局兜底。
- **Q9 Supervisor 时机与路由**：P2b 有第二个 coach（写作）时加，先按确定信号路由，只有自由对话才调一次轻量分类。
- **Q10 写作入口**：独立 `/writing` 页 + 对话里贴作文由 writing_coach 批改，两边共用同一服务和记录。
- **Q11 每日计划确认**：复用确认卡（和换词书一致，可撤销）。
- **Q12 后台调用**：租户级每日 token 上限（默认保守，设置页可改）+ 每个后台功能学习者可关，默认开启诊断和文章改写、关闭 AI 例句预生成。
- **Q13 评估集**：P2a 就建 `backend/evals/` 的最小集（critic 拒坏题、批改判已知答案，默认用录制的假模型跑，可选真实模型），P4 再接 CI 回归和看板。
