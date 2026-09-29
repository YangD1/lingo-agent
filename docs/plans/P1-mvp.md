# P1 MVP · 详细实施计划

> 状态：**已确认**（2026-09-29，Q1–Q14 全部按推荐；Q11–Q14 是同日追加的“个人能力看板 + AI 建议 + 直达学习”，见 §7.5、子阶段 P1e）。
> 上位设计见 `docs/PLAN.md` 第二·五节、第三节和第四节 P1。本文件只写 P1 范围内“怎么做”，超出 P1 的只留接口、不实现。
> 相关 ADR（已采纳）：0009 长期记忆、0010 学习者模型、0011 词库与背词调度。

## 0. P1 的完成定义（Demo 脚本）

在 P0 Demo 的基础上（已注册、已配好模型）：

1. **入学测**：首次进入后被引导做入学测（约 10 分钟，可跳过）。先做词汇量测试（认识/不认识，混有假词），再做语法/阅读自适应选择题，题目难度随作答变化。结束后看到 CEFR 等级估计（总体 + 词汇、语法两个维度）和估计词汇量。
2. **背单词**：选一本词书（比如 CET4）→ 做熟词筛选，“认识”的词直接跳过 → 进入今日学习：新词 + 到期复习，按 Again/Hard/Good/Easy 评分。第二天打开时，到期的词按 FSRS 排好。词书页能看到进度（“CET4 已学 12%”）。
3. **带记忆的对话**：聊天时提到“我是做后端开发的，下个月要面试”。几轮之后打开“AI 记住了你什么”页面，能看到这条事实，并且可以编辑、删除。**新建一个会话**，问“帮我练练面试”，回复里用到了这条信息。
4. **错误打标 → 学习者模型**：对话里故意写错几次，比如 `I have went there yesterday`。在“学习者模型”页上看到对应语法点（如“现在完成时 vs 一般过去时”）的掌握度下降，并能展开看到证据：原句、改正、来自哪个会话。
5. **自动收词**：对话里问“what does *reluctant* mean”，这个词会进入“我的生词本”，优先于词书里的词出现。
6. **能力看板**：登录后首页是能力看板，能看到 CEFR 等级、估计词汇量、词书进度（环形图）、各等级语法点掌握情况、最近常错的语法点和学习打卡热力图；下方有 2–3 条 AI 建议（例如“你有 32 个词到期，先复习”“现在完成时最近错了 5 次，来一次针对练习”），点一下直接进入对应的复习页、入学测或针对某个语法点的练习对话。
7. 回复不会因为记忆抽取和错误打标而变慢：这些都在回复结束后于后台完成。
8. `make test`、`make lint`、`make e2e` 全绿；GitHub Actions 全绿。

**P1 不做**（留到 P2 及以后）：LLM 出练习题和 critic 校验、诊断 Agent（根因分析）、语法知识图谱（Neo4j）、多题型练习页、个性化例句/记忆法（`word_enrichment_cache`）、拼写/听音等背词题型、写作批改、阅读、APScheduler 定时任务、语音朗读。

---

## 1. 范围与子阶段

P1 拆成五个子阶段，每个子阶段结束都能单独演示（Q1）：

| 子阶段 | 内容 | 依赖 | 对应 Demo |
|---|---|---|---|
| **P1a** 记忆 | 主图改造（load_context → tutor → END）+ 后台反思（reflect）+ 长期记忆（事实记忆、会话摘要）+ 学习者画像 + “AI 记住了你什么”页面 | P0 对话图 | 3、6 |
| **P1b** 学习者模型 | 语法 KC 清单 + 反思里的错误打标 → `kc_evidence` → BKT 更新 `kc_mastery` + 学习者模型页 | P1a 的 reflect | 4 |
| **P1c** 背单词 | ECDICT 导入、词书、熟词筛选、FSRS 复习页、生词本（含对话自动收词） | P1a 的 reflect（只影响自动收词） | 2、5 |
| **P1d** 入学测 | 词汇量测试 + 语法/阅读自适应测试（LangGraph 子图 + interrupt）、结果写画像和 `skill_estimates`、为 KC 掌握度设先验 | P1b 的 KC 清单、P1c 的词库 | 1 |
| **P1e** 能力看板 | 能力看板页（图表）+ AI 学习建议（算法出候选、LLM 写理由）+ 直达学习（含针对语法点的练习对话） | P1a–P1d 的全部数据 | 6 |

---

## 2. 新增依赖

| 包 | 版本 | 用途 | 内存/体积 |
|---|---|---|---|
| fsrs | 6.3（2026-08-09，MIT） | FSRS-6 调度（`Scheduler.review_card`） | 核心只依赖 `typing-extensions`；**不装 `[optimizer]` extra**（会拉 torch/numpy/pandas） |

- BKT 和 Elo 的更新公式各约 30 行，**自己写**，只用标准库（pyBKT 依赖 numpy / scikit-learn / pandas，只有离线拟合参数才用得上，P1 不引入）。
- 长期记忆**不引入 LangMem**：最新发布是 0.0.30（2025-10），近一年没有新版本，依赖又重（trustcall、langsmith 等）。借鉴它的“提取 → 增/改/删操作”思路，自己用结构化输出实现（ADR 0009）。
- ECDICT 数据文件不进仓库，由导入脚本下载（§5.1）。
- 前端：P1e 新增 shadcn/ui 的 chart 组件（依赖 Recharts，只在浏览器里渲染，Q14）；其余不新增（`react-markdown` 已有；单词发音用浏览器自带的 `speechSynthesis`）。

---

## 3. 主图与后台反思（P1a，ADR 0009）

### 3.1 图结构

```
START → load_context → tutor → END
```

- `load_context`：读学习者画像、事实记忆、相关的会话摘要、学习者模型摘要（最弱的几个 KC、今天到期的词数），拼成一段“关于这个学习者”的上下文。**只放进本次调用的 system prompt，不写进 checkpoint**（和附件的处理方式一致，见 ADR 0008），这样记忆被用户删了之后立刻生效。
- `tutor`：同 P0，system prompt 多了学习者上下文。
- **Supervisor / 意图路由推迟到 P2**（Q2）：P1 的对话里只有 tutor 一个角色，入学测和背单词都是独立页面，不走聊天。现在加 LLM 路由，每轮会多一次调用和延迟，却没有第二个分支可去。图的结构按“以后在 load_context 和各个 coach 之间插路由节点”来写，P2 有了 grammar / writing / reading coach 再加。PLAN 第四节 P1 的“Supervisor 主图”相应改为 P2。

### 3.2 后台反思（reflect）

回复完成（SSE 发出 `done`）后，把这一轮交给进程内的 `ReflectionWorker`（仿照 `AttachmentProcessor`：单 worker、进程内 task、不引入队列）。

- **一次结构化调用做三件事**（Q4），路由 task 名 `reflect`（没配时按 ADR 0007 用默认模型兜底）：
  ```python
  class Reflection(BaseModel):
      memory_ops: list[MemoryOp]          # 事实记忆的 add / update / delete（带已有记忆的 id）
      profile_updates: ProfileUpdate | None  # 目标、兴趣、职业等画像字段有明确变化时才给
      mistakes: list[TaggedMistake]       # 学习者这一轮英文里的错误，kc_id 必须来自 KC 清单
      used_correctly: list[str]           # 这一轮在自由表达中用对的 KC（产出证据，§4.3）
      vocab_candidates: list[str]         # 学习者问过、明显不认识的词（原形）
  ```
  输入：本轮学习者消息和回复、现有事实记忆（带 id）、KC 清单（id + 简短描述）。KC 清单放在 prompt 前部固定不变，便于厂商的前缀缓存。
- 输出校验：`kc_id` 不在清单里的错误丢弃并记日志；`vocab_candidates` 查不到 ECDICT 的丢弃。**这些都是结构化输出 + 代码校验，不靠正则。**
- **会话摘要**：每个会话一条情景记忆，每 6 轮（和学习者新建另一个会话时）重写一次，覆盖旧摘要；和记忆抽取共用 `reflect` 路由（任务 4 落地时合并，见 ADR 0009 落地记录）。
- **按会话串行**：同一会话的反思排队执行，不同会话并发（全局信号量，默认 2）。
- **进程重启不丢**：`conversations.reflected_message_id` 记录已反思到哪条消息；worker 启动时和每次新消息到来时，从这个位置补做。
- 反思失败只记日志和 `llm_usage`，不影响对话；不重试超过 1 次。

### 3.3 测试

- 图：假模型跑 `load_context → tutor`，断言 system prompt 里有学习者上下文、checkpoint 里没有。
- reflect：假结构化模型返回固定 `Reflection`，断言记忆增删改、`kc_evidence` 入库、非法 kc_id 被丢弃、`reflected_message_id` 前移；worker 串行和补做逻辑单测。
- SSE 集成测试：`done` 事件在反思完成之前发出（反思用一个会阻塞的假模型）。

---

## 4. 学习者模型（P1b，ADR 0010）

### 4.1 KC 清单

- **语法 KC**：`backend/app/adaptive/kc/grammar.yaml`，约 80–120 个语法点，每个有 `id`（如 `g.present_perfect_vs_past_simple`，稳定不改）、中英文名、CEFR 等级、前置 KC、常见错误类型。**P2 的 Neo4j 图谱沿用同一套 id**（Q5）。
  - 内容自己编写（按 CEFR 等级组织的通用语法点），不照抄 English Grammar Profile 等有版权的清单。初稿由 LLM 起草，**人工审核后提交**。
- **单词 KC**：`w.<lemma>`，直接对应 `words` 表，不单独建清单。
- 技能维度（listening / speaking / reading / writing / grammar / vocab）用 `skill_estimates`，不是 KC。

### 4.2 掌握度：BKT（每个 KC）+ Elo（能力值和题目难度）（Q6）

- **语法 KC 的掌握度用 BKT**：可解释的“学会的概率”，`p_mastery ≥ 0.95` 有清楚的含义。参数先用全局默认值（`p_init` 按 KC 的 CEFR 等级和学习者等级给，`p_learn=0.1`、`p_guess=0.2`、`p_slip=0.1`），P4 有了数据再离线用 pyBKT 拟合。
- **入学测和技能估计用 Elo**（Pelánek 2016，K 随作答次数衰减：`K(n) = α / (1 + β·n)`）：同时估计学习者能力和题目难度，冷启动好，适合入学测的自适应选题。
- **单词不用 BKT**：单词的“记住没有”由 FSRS 的可提取性（retrievability）表示，`kc_mastery` 里单词行的 `p_mastery` 直接取 FSRS 的值，避免两套模型打架。
- **LLM 只提供证据，不打分**：LLM 输出“这句话错在哪个 KC”，掌握度由 BKT 根据证据计算。

### 4.3 证据权重

| 证据 | 来源（P1） | BKT 观测 |
|---|---|---|
| 自由表达中出错 | reflect 的 `mistakes` | 错误（严重度低的只记录、不更新） |
| 自由表达中用对 | reflect 的 `used_correctly` | 正确，**但 `p_guess` 调低**：产出比识别更难靠猜 |
| 入学测答对/答错 | P1d | 正确/错误（识别类证据） |

同一轮对同一 KC 最多计一次观测，防止一句话里重复犯同一个错被连扣多次。

PLAN §二·五 第 7 条的“学会”判定（≥3 种题型、跨 ≥2 天）需要练习题，P2 才能完整实现；P1 只计算 `p_mastery` 并记下 `recog_correct` / `produce_correct` 计数。

### 4.4 表

- `kc_mastery`（user_id、kc_id、kind[word/grammar]、p_mastery、observations、recog_correct、produce_correct、last_evidence_at；唯一键 user_id + kc_id）
- `kc_evidence`（只追加，ADR 0012）：user_id、kc_id、correct、evidence[recognition/production]、source[chat/placement]、conversation_id（可空，会话删除时置空）、message_id、created_at；错误行另有 error_type、severity[low/medium/high]、original、correction、l1_transfer
- `kc_mastery` 另存 `rules_version`，可由证据重放重算
- `skill_estimates`（user_id、skill、rating、attempts、updated_at；不确定度由 attempts 现算）

### 4.5 测试

BKT、Elo 纯函数单测（边界：概率在 [0,1]、连续答对收敛、K 衰减）；证据去重；reflect → kc_evidence → kc_mastery 的集成测试。

---

## 5. 背单词（P1c，ADR 0011）

### 5.1 词库导入

- **来源**：ECDICT（MIT）。`ecdict.csv` 66 MB、约 77 万条，其中绝大多数是短语和生僻词。
- **导入子集**（Q7）：有考试标签（zk/gk/cet4/cet6/ky/toefl/ielts/gre）、或 `oxford=1`、或 `collins>0`、或 `bnc`/`frq` 排名在前 30000 的行，预计约 2–3 万条。只导入需要的列：word、phonetic、translation、definition、pos、collins、oxford、tag、bnc、frq、exchange。
- **导入方式**：`make vocab-import` → `python -m app.services.vocab.import_ecdict`：下载 CSV 到 `data/`（已 gitignore），流式逐行过滤（不整份读进内存），`COPY` 写入 `words` 表；可重复执行（按 word upsert）。Docker 里用 `docker compose exec backend ...`。测试用仓库里的一份几十行的小 CSV。
- `lemma.en.txt` 暂不导入；词形还原用 `exchange` 字段（如 `went` → `0:go`）。
- **词书**：由 `tag` 生成的虚拟词书（`word_books` 只存 id、名称、tag），不复制词表。

### 5.2 调度

- `user_cards`：user_id、word_id、source[book/auto/manual]、status[new/learning/known/suspended]、FSRS 状态（state、step、stability、difficulty、due、last_review，对应 `fsrs.Card.to_dict()` 的字段），唯一键 user_id + word_id。
- `review_logs`：card_id、rating、reviewed_at、review_duration_ms、调度前后的状态快照（以后拟合参数用）。
- `user_word_book`：user_id、book_id、daily_new（默认 15）、created_at。
- **每日队列**：到期复习（按 due 排序）→ 生词本里的新词（source=auto/manual，优先）→ 词书新词（按 `frq` 排名升序，跳过 known）。新词数受 `daily_new` 限制，复习不限。
- `desired_retention=0.9`，时间一律 UTC，“今天”按用户时区切分（用户画像里存时区，默认取浏览器上报的值）。
- **熟词筛选**：一次给 50 个词（按词频从高到低，跨度大），选“认识”的记为 `known`，不进复习队列；认识比例高时自动跳到更低频的词段。筛选可以随时再做。

### 5.3 页面

- `/vocab`：选词书、进度（已学/已认识/总数）、今日任务数、入口
- `/vocab/screen`：熟词筛选
- `/vocab/review`：卡片（先显示单词 → 回想 → 翻面显示音标、中文释义、英文释义 → 四个评分按钮），键盘快捷键 1–4、空格翻面，`speechSynthesis` 读单词
- `/vocab/mine`：我的生词本（自动收词和手动添加），可删除
- 聊天回复里选中文字可以“加入生词本”（P1c 的最后一个任务，Q9）

### 5.4 测试

队列生成（到期、新词上限、优先级）、FSRS 状态的存取往返、导入过滤（小 CSV）、时区切分。

---

## 6. 入学测（P1d，ADR 0010）

### 6.1 两部分（Q8）

1. **词汇量测试**（纯算法，不调 LLM）：按 `frq` 排名分成若干频段，每题给一个词，回答“认识/不认识”，其中约 25% 是**假词**。假词由程序生成（按真实单词的字母转移概率生成，再过滤掉 ECDICT 里存在的词），不用 LLM。按假词的误报率校正后估计词汇量，频段用 Elo 自适应选择。约 40 题、3 分钟。
2. **语法/阅读自适应测试**：四选一，题目来自**仓库里的静态题库** `backend/app/adaptive/placement/items.yaml`（A1–C2，约 90 题，每题标 KC id 和初始难度）。用 Elo 选题：每次选预估正确率最接近 50%–60% 的题，能力值的不确定度足够小或满 20 题就停。
   - 为什么用静态题库、不用 LLM 现场出题：入学测结果决定后面所有内容的难度，题目错一道影响很大；按项目约束，LLM 出的题必须经过 critic，而 critic 是 P2 的内容。题库初稿由 LLM 起草，**人工逐题审核后提交**。P2 有了 critic 之后，可以用它扩充题库。

### 6.2 实现

- `placement` 子图：`pick_item → ask（interrupt，等作答）→ update_estimate → 结束判定 → (pick_item | finish)`。每次作答用 `Command(resume=answer)` 恢复。选题和更新都是纯函数，图只负责编排和断点续做（关掉页面再回来能接着做）。
- 独立接口 `POST /placement`（开始或继续）、`POST /placement/{id}/answer`、`GET /placement/{id}/result`，不走聊天 SSE。
- 结果写入：`user_profile.cefr_level`、`skill_estimates`（vocab、grammar）、按等级给语法 KC 设 BKT 先验（等级以下的 KC 先验高）、`kc_evidence`（source=placement，每道题一条识别证据）。词汇量结果只用来建议熟词筛选从哪个频段开始，不自动把词标成已认识。
- CEFR 映射：Elo 能力值 → CEFR 的分界点写在配置里，初值按题库难度标定，之后再调。

### 6.3 页面

`/placement`：说明页 → 词汇量测试 → 语法测试 → 结果页（等级、分项、估计词汇量、“去选词书”入口）。首次登录且没有测过时，聊天页顶部显示引导条（可关闭）。

---

## 7. 学习者画像与记忆页面（P1a / P1b）

- `user_profile`（user_id PK、native_language、goal、target_exam、interests（文本数组）、occupation、daily_minutes、explanation_language[zh/en]、cefr_level、timezone、updated_at）：设置里可以直接编辑；reflect 只在对话里出现明确信息时更新，用户手动改过的字段 reflect 不再覆盖（记录 `manual_fields`）。
- `/memory`（“AI 记住了你什么”）三个区块：
  1. **画像**：表单，可编辑
  2. **事实记忆**：列表，可编辑、删除、全部清空；显示来源会话和时间
  3. **会话摘要**：列表，可删除
- `/learner`（学习者模型）：只列接触过的语法 KC（有证据的），薄弱在前，可按等级、状态（已掌握 ≥ `bkt.mastered` / 学习中 / 薄弱 < `bkt.weak`）筛选，每个等级显示“接触 seen/total”；展开看证据（错误和用对，标出是否计入 BKT、来源会话），可删单条（重算该 KC，并从对应消息的 `grammar_tagging` 活动里去掉）；技能估计；“删除所有学习记录”（证据、掌握度、技能估计和全部 `grammar_tagging` 活动，不动画像里的 CEFR 等级）。`/learner?kc=<id>` 直达并展开。接口：`GET /learner`、`GET /learner/kcs/{kc_id}/evidence`、`DELETE /learner/evidence/{id}`、`DELETE /learner`。
- 删除是真删除（隐私要求），不做软删除。

---

## 7.5 能力看板、AI 建议与直达学习（P1e，2026-09-29 追加）

### 7.5.1 看板内容（Q11）

图表按“数据是什么形状”选，不为了好看硬用饼图：只有“部分占整体”的数据用环形图。

| 区块 | 数据 | 图表 |
|---|---|---|
| 总览卡片 | CEFR 等级（入学测 + 持续更新）、估计词汇量、连续学习天数、今日待复习数 | 数字卡片 |
| 词书进度 | 当前词书中 已掌握 / 学习中 / 未学 / 熟词跳过 的数量 | **环形图**（部分占整体） |
| 语法掌握 | 按 CEFR 等级（A1–C2）统计语法点的 已掌握（p≥0.95）/ 学习中 / 薄弱（p<0.4）/ 未接触 | 横向堆叠条形图 |
| 技能估计 | `skill_estimates` 里**有数据的**维度（P1 只有词汇、语法），其余显示“未评估”和对应入口 | 带 CEFR 刻度的条形图 |
| 常错语法点 | 最近 30 天 `kc_evidence` 里的错误按 KC 计数的前 5 个，点击进入 `/learner` 对应条目 | 条形图 |
| 学习打卡 | 最近 12 周每天的复习数 + 对话轮数 | 日历热力图 |

- P1 **不做六维雷达图**：听、说、读、写要到 P2/P3 才有数据，只有两个维度有值的雷达图会误导。等维度齐了再换成雷达图。
- 没有数据时（新用户）每个区块显示引导，而不是空图：比如“做入学测，看你的等级”。
- 数据由一个聚合接口 `GET /dashboard` 返回，纯 SQL 聚合，不调 LLM。

### 7.5.2 AI 建议（Q12）

遵守“算法负责记账和调度，LLM 负责理解和生成”：**做什么由算法决定，LLM 只负责挑选和写理由**。

1. **候选动作（算法）**：按规则生成带证据的候选，每个候选有固定的动作类型和参数：
   | 动作 | 触发条件 | 直达 |
   |---|---|---|
   | `vocab_review` | 有到期的词 | `/vocab/review` |
   | `vocab_learn` | 今天的新词还没学完 | `/vocab/review?mode=new` |
   | `vocab_screen` | 选了词书但还没做过熟词筛选 | `/vocab/screen` |
   | `placement` | 从未做过入学测，或上次超过 60 天 | `/placement` |
   | `grammar_practice` | 某语法点 p_mastery 低且最近有错误 | 新建针对该语法点的练习对话 |
   | `choose_book` | 还没选词书 | `/vocab` |
   按 薄弱度 × 紧迫度 排序，取前 6 个。
2. **LLM 挑选并写理由**（路由 task `advice`，结构化输出）：输入候选列表（带证据：到期数、错误原句示例、掌握度）和学习者画像（目标、每日时长、兴趣），输出最多 3 条 `{candidate_id, title, reason}`。**`candidate_id` 必须来自候选列表**，由代码校验，不在列表里的丢弃；所以 LLM 编不出不存在的链接或语法点。
3. **缓存**：结果存 `learning_advice` 表（每人一行）。打开看板时直接读缓存；缓存超过 12 小时、或之后新增的证据（复习、错误）超过阈值时，在后台重新生成，页面先显示旧建议。有“刷新建议”按钮（限每小时一次）。**不是每次打开看板都调 LLM。**
4. **没配模型或调用失败**：直接用候选列表的前 3 个和模板文案（i18n），看板照常可用。

### 7.5.3 针对语法点的练习对话

- `grammar_practice` 会新建一个会话，`conversations.focus_kc_id` 记下语法点，标题为“练习：<语法点>”。
- `load_context` 看到 `focus_kc_id` 时，在 system prompt 里加入练习指引：简短讲解，然后通过对话引导学习者**自己说出**用到这个语法点的句子，并当场纠正。反思照常进行，所以这里的对错会作为产出证据更新掌握度。
- 这是对话，不是出题：P1 不生成带标准答案、要评分的题目（按项目约束，这类题要过 critic，放到 P2 的练习页）。

### 7.5.4 页面与导航（Q13）

- 登录后的首页改为 `/dashboard`（现在是 `/chat`），顶部导航：看板 / 对话 / 单词 / 学习者模型 / 设置。
- 图表用 shadcn/ui 的 chart 组件（基于 Recharts，Q14）。图表只在浏览器里渲染，不增加服务器内存。颜色随亮/暗主题变化，每个图表都有文字说明，不只靠颜色区分。

---

## 8. 表汇总与迁移

新增：`user_profile`、`memories`、`kc_mastery`、`kc_evidence`、`skill_estimates`、`words`、`word_books`、`user_word_book`、`user_cards`、`review_logs`、`placement_sessions`（placement 子图的 thread 和状态）、`learning_advice`（每人一行：建议 JSON、生成时间、生成时的证据计数）。`conversations` 加 `reflected_message_id`、`focus_kc_id`。

- 每个子阶段一个迁移，不一次建完。
- 所有用户数据表都有 `user_id` FK（级联删除），查询一律带 user_id 过滤；`words`、`word_books` 是全局只读数据。
- `memories.embedding` 用不带维度的 `vector` 列（可空），另存 `embedding_model`；每个用户的记忆只有几十到几百条，直接按用户过滤后精确计算距离，不建 ANN 索引（ADR 0009）。

---

## 9. 任务顺序

每项的完成标准：对应测试通过、lint 干净、看板已更新。

| # | 任务 | 验证 |
|---|---|---|
| 0 | 11C 第 3、4 条（Q10）：语音转写连接的“测试”按转写来测；Speaches 预设在 Docker 下的默认地址 | 单测 + 手动 |
| 1 | ADR 0009、0010、0011 定稿；PLAN 同步（Supervisor 移到 P2、数据模型更新） | 人工 review |
| **P1a** | | |
| 2 | `user_profile` + `memories` 表和迁移；记忆的服务层（增删改查、按用户隔离）；记忆检索（有 embedding 路由时按向量，否则按时间） | 单测 + 集成测试 |
| 3 | `load_context` 节点 + 主图改造；学习者上下文的拼装和长度上限 | 图测试：上下文进了 prompt、没进 checkpoint |
| 4 | `ReflectionWorker` + `reflect` 结构化调用（先只做 memory_ops、profile_updates）+ 会话摘要 + `reflected_message_id` 补做 | 集成测试：`done` 不等反思；重启补做 |
| 5 | 记忆和画像接口 + `/memory` 页面（i18n）+ 设置页路由编辑器加入 `reflect`（“后台整理模型”） | Vitest + E2E：聊天 → 记忆出现 → 删除 → 新会话不再使用 |
| **P1b** | | |
| 6 | 语法 KC 清单（LLM 起草 → 用户审核）+ 加载和校验（id 唯一、前置 KC 存在、无环） | 单测 |
| 7 | BKT / Elo 纯函数 + `rules.yaml` + `kc_mastery`、`kc_evidence`、`skill_estimates` 表 | 单测 |
| 8 | reflect 加上 mistakes、used_correctly → 证据去重 → BKT 更新 | 集成测试 |
| 8b | agent 活动公示（ADR 0013）：活动记录表 + 对话步骤和后台反思写入 + SSE 推送 + 每条回复下可展开的“私教做了什么” + 设置里可隐藏 | 集成测试 + Vitest + E2E |
| 9 | 学习者模型接口 + `/learner` 页面 | Vitest + E2E |
| **P1c** | | |
| 10 | `words` 表 + ECDICT 导入脚本 + `make vocab-import` | 小 CSV 单测；真实数据导入一次，记录条数、耗时、库大小 |
| 11 | 词书、`user_cards`、`review_logs` + FSRS 调度服务 + 每日队列 | 单测 |
| 12 | 背词接口 + `/vocab`、`/vocab/screen`、`/vocab/review`、`/vocab/mine` 页面 | Vitest + E2E |
| 13 | reflect 的 vocab_candidates → 生词本；聊天里选中文字加入生词本 | 集成测试 + E2E |
| **P1d** | | |
| 14 | 语法题库（LLM 起草 → 用户审核）+ 假词生成器 + 词汇量估计 | 单测（假词不在词库里、估计单调） |
| 15 | placement 子图（interrupt / resume）+ 接口 + 结果写回 | 集成测试：中途退出后继续 |
| 16 | `/placement` 页面 + 聊天页引导条 | Vitest + E2E |
| **P1e** | | |
| 17 | `GET /dashboard` 聚合接口 + `/dashboard` 页面（图表、空状态、导航调整、首页改为看板） | 聚合查询集成测试；Vitest；E2E（新用户空状态、有数据时各图表出现） |
| 18 | 建议候选算法 + `advice` 结构化调用 + `learning_advice` 缓存与后台刷新 + 模板兜底 | 单测（候选规则、id 校验、兜底）；集成测试（缓存命中不调 LLM） |
| 19 | 针对语法点的练习对话（`focus_kc_id` + load_context 练习指引）+ 建议卡片直达 | 图测试；E2E：点建议 → 进入练习会话 |
| 20 | P1 Demo 全流程实测 + README 更新 | 用户实测 |

---

## 10. 待确认的决定

以下 Q1–Q10 已确认（2026-09-29，全部按推荐）。

- **Q1 子阶段顺序**：推荐 **P1a 记忆 → P1b 学习者模型 → P1c 背单词 → P1d 入学测**。前两个是“Agent 能力”的核心，后两个依赖 KC 清单和 reflect。备选：先做 P1c 背单词（最独立、日常最常用），再做其他。
- **Q2 Supervisor**：推荐 **P1 不加意图路由**，主图是 `load_context → tutor`，路由推迟到 P2 有第二个 coach 时再加（理由见 §3.1）。备选：P1 就加 LLM 路由（tutor / vocab_coach），vocab_coach 通过工具查词、加生词本。
- **Q3 记忆存储**：推荐 **自建 `memories` 表**（ADR 0009）。关键原因：embedding 是租户各自配置的，不同租户的模型和向量维度不同；而 LangGraph Store 的语义索引在创建时就固定了一个 embedding 函数和维度（`index={"dims", "embed"}`），一个进程里的多个租户用不了。另外，自建表能用 FK 级联删除、Alembic 管理、方便做编辑页面。备选：LangGraph `AsyncPostgresStore`，不开语义索引，只按 namespace 读全部记忆。
- **Q4 反思调用**：推荐 **每轮一次结构化调用，同时做记忆、画像、错误打标、收词**（省调用次数，KC 清单放在固定前缀里利于缓存）。备选：拆成两个调用（记忆一个、错误打标一个），各自 prompt 更简单，但调用次数翻倍。
- **Q5 KC id**：推荐 **P1 先写静态语法 KC 清单（YAML）**，P2 的 Neo4j 图谱沿用这些 id。备选：P1 就上 Neo4j（要多占约 1G 内存，且 P1 用不到图遍历）。
- **Q6 掌握度模型**：推荐 **语法 KC 用 BKT，入学测和技能估计用 Elo，单词用 FSRS 的可提取性**（§4.2）。备选：全部用 Elo（更简单，但没有“学会的概率”这个直观量）。
- **Q7 词库范围**：推荐 **导入有标签 / 牛津 / 柯林斯 / 词频前 3 万的子集**（约 2–3 万条）。备选：全量 77 万条（库里多几百 MB，绝大多数用不到）。
- **Q8 入学测**：推荐 **词汇量测试（假词校正）+ 静态语法题库的 Elo 自适应测试**，不做写作/口语样本评估。备选：加一段写作样本，由 LLM 按评分量表给等级（更全面，但入学测结果会依赖 LLM 的稳定性）。
- **Q9 背词题型**：推荐 **P1 只做翻卡片（回想 → 自评）**，拼写、听音辨词、个性化例句放到 P2。备选：P1 就加拼写题。
- **Q10 11C**：推荐 **P1 开工前先修第 3、4 条**（Speaches 默认地址是一行改动；转写连接的“测试”按钮会让配置出错时有明确提示）。第 1、2、5 条仍然暂缓。

**追加需求（能力看板）：已确认（2026-09-29，全部按推荐）**

- **Q11 看板图表**：推荐 **§7.5.1 的组合**：环形图只用于词书进度这种“部分占整体”的数据，语法和技能用条形图，打卡用热力图；P1 不做雷达图（只有两个维度有数据）。备选：六维雷达图，未评估的维度显示为空。
- **Q12 AI 建议怎么生成**：推荐 **算法出候选动作 + LLM 挑选并写理由，结果缓存、后台刷新**（§7.5.2），链接和语法点都不会是编出来的，也不会每次打开看板都花一次调用。备选：LLM 直接根据学习数据自由写建议，每次打开都生成。
- **Q13 首页**：推荐 **登录后默认进看板**，对话放在导航里。备选：保持现在默认进对话，看板作为一个导航项。
- **Q14 图表库**：推荐 **shadcn/ui 的 chart 组件（Recharts）**，和现有组件风格一致，只增加前端包体积。备选：手写 SVG（零依赖，但热力图、堆叠条形图的交互和无障碍要自己做）。
