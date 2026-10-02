# lingo-agent 方案设计（已确认 2026-09-28）

> 开源项目。本文件是方案的唯一权威来源；变更须同步更新并在 docs/decisions/ 记录原因。

## Context

- **目标**：一个真正可用的 AI 英语私教，同时作为企业级 Agent 应用的完整参考实现：LangChain / LangGraph / 可插拔 OpenTelemetry 观测 / GraphRAG / 用户长期记忆 / 定时自主任务 / 语音。
- **已确认的约束**
  - LLM：默认支持 DeepSeek、Claude、OpenAI，通过可配置的 provider 层扩展（兼容所有 OpenAI 协议厂商：通义、GLM、Ollama 等）。
  - 前端：Next.js Web。
  - 服务器配置很低：线上语音走（尽量免费的）API，开发环境走本地模型，**用配置切换**。
  - 目标：两者兼顾、长期迭代，分阶段交付，每个阶段结束都能用、能演示。

---

## 一、需求分析与补充

| 模块 | 初始需求 | 扩展设计 |
|---|---|---|
| **长期记忆** | 用户长记忆 | 拆成三类：①**画像/语义记忆**（目标、兴趣、母语干扰、偏好讲解风格）②**情景记忆**（“上周聊过面试，卡在自我介绍”）③**结构化学习者模型**（词汇掌握度、语法薄弱点、CEFR 等级——放关系库，不能只靠向量检索）。支持用户查看、编辑、删除自己的记忆（隐私合规加分项） |
| **能力评估** | 英语能力评估 | 按 CEFR A1–C2 分级；**入学测**（自适应出题，按 Elo/简化 IRT 调难度）+ **持续评估**（日常对话、写作、做题结果都回写能力值）；听说读写分维度雷达图；周报/月报 |
| **语法** | 语法学习 | 语法知识图谱（知识点→前置依赖→常见错误）；**错因溯源**（“你的虚拟语气错误根源是时态一致没掌握”）；错题本 + 针对性变式题 |
| **阅读** | 定时/即时爬新闻 | 来源用 RSS：内置 NASA 新闻稿（公有领域）和 Global Voices（CC BY），加学习者自加的 RSS，界面显示出处和许可（ADR 0024；原定的 VOA Learning English 已停更）；**按用户 CEFR 等级分级改写**、生词自动标注并一键加入词本、阅读理解题、长难句拆解 |
| **背单词** | 类墨墨记忆曲线 | 墨墨算法闭源 → 用开源 **FSRS**（Anki 新版在用，可讲清 DSR 记忆模型：难度/稳定性/可提取性）；词从阅读、对话中自动收集；AI 生成个性化例句（结合用户兴趣）；拼写、听音辨词、释义多题型 |
| **语音** | 朗读、对话 | ASR + TTS 双 provider（本地/API 可切）；跟读 + **发音评测**（音素级打分）；情景口语角色扮演（面试、点餐、会议） |
| **多模态输入**（新增，ADR 0008） | — | 消息可带图片、语音、文档（含扫描版 PDF）；每个附件生成一份派生文本（看图识别 / 语音转写 / 文字抽取），对话、记忆、错题、以后的文档 RAG 都读它；原图只在发送的那一轮随消息发给 `vision` 路由的模型 |
| **写作**（新增） | — | 作文/邮件批改：错误标注、改写、分数；错误回写到学习者模型 |
| **主动 Agent**（新增） | — | 每日学习计划生成（需用户确认，展示 human-in-the-loop）、复习到期提醒、周报 |
| **企业级要素**（新增） | — | 多租户（个人租户，预留组织）+ 租户自配模型凭据（加密存储、SSRF 防护）、多用户鉴权、OpenTelemetry 链路追踪（默认关闭，开发时用本地 Phoenix）与**离线评估集**（批改准确率/分级准确率/幻觉率，pytest 驱动）、租户可见的 token 用量统计（`llm_usage`）、模型路由（便宜模型做分类，强模型做讲解）、限流、提示词版本管理、Docker 一键部署、CI |

---

## 二、总体架构

```
Next.js (App Router, TS, Tailwind, shadcn/ui；视觉系统与深色主题见 ADR 0019)
   │  REST + SSE（流式对话）+ WebSocket（语音）
FastAPI (Python 3.12, uv)
   ├── LangGraph 主图（Supervisor 多 Agent；P1 先是 load_context → tutor，路由在 P2b 加入，见 ADR 0009、0023）
   │     ├─ 路由（先看会话类型等确定信号，只有自由对话才调轻量分类）→ tutor_chat | grammar_coach | reading_coach
   │     │                    vocab_coach | speaking_coach | writing_coach | assessor
   │     ├─ pre: load_memory（画像 + 相关情景记忆 + 学习者模型摘要）
   │     └─ post: reflect_memory（后台异步抽取/合并记忆，不阻塞回复）
   ├── Provider 层：LLM / Embedding / ASR / TTS / 发音评测，全部配置驱动
   ├── 领域服务：FSRS 调度、CEFR 评估、新闻抓取与分级改写
   └── 调度器：APScheduler 进程内、单实例（低配服务器友好，不上 Celery；后台模型调用有租户每日上限，见 ADR 0025）
存储
   ├── PostgreSQL 16 + pgvector：业务数据、学习者模型、向量、LangGraph checkpointer、语法知识图谱（`kc_edges` + 递归查询，ADR 0022）
   └── Redis（可选，限流/缓存；低配可关）
可观测（ADR 0005）：自建 llm_usage 用量表（租户可见）+ 可选 OpenTelemetry tracing（OTLP 导出，dev 用本地 Phoenix；不绑定厂商）
```

### “provider” 解释
provider = 模型供应商适配层（配置格式、路由与降级语义见 ADR 0002；**key 由租户在应用内配置并加密存库，租户可自定义 base_url、模型和路由，见 ADR 0004；连接可自动发现模型、设默认模型，路由匹配不上时自动用默认模型兜底，见 ADR 0007；看图用 `llm.vision` 路由、语音转写用 `asr` 一节，都走租户连接且不自动兜底，见 ADR 0008**）。代码只调用统一接口（`get_llm("tutor")`），实际用哪家由 YAML/环境变量决定。LangChain 的 `init_chat_model` + OpenAI 兼容 `base_url` 可以覆盖 DeepSeek / Claude / OpenAI / 通义 / GLM / Ollama。再按**任务**配置模型：
```yaml
llm:
  default: deepseek:deepseek-chat
  routes:
    router: deepseek:deepseek-chat         # 意图分类，便宜
    tutor: anthropic:claude-sonnet-5         # 讲解质量
    memory_extract: openai:gpt-4o-mini
    vision: anthropic:claude-sonnet-5       # 读图、回复带图的那一轮（ADR 0008）
asr:                                        # OpenAI 兼容 /audio/transcriptions，走租户连接（ADR 0008）
  default: [groq:whisper-large-v3-turbo, siliconflow:FunAudioLLM/SenseVoiceSmall, openai:gpt-transcribe]  # 大陆访问不了 Groq/OpenAI 时用硅基流动；dev 可改为本地 speaches 连接
speech:
  tts: browser               # 默认浏览器朗读（挑好声音）；可选租户连接：兼容 OpenAI 的 /audio/speech 或 Azure 语音（ADR 0018）
  pronunciation: azure        # 免费档 F0 每月 5 小时；本地方案后置
  realtime: gemini_live       # 端到端语音对话；可选 openai_realtime / disabled
```

### 技术栈各自落在哪
| 技术 | 用在哪里 |
|---|---|
| **LangChain** | provider 抽象、结构化输出（Pydantic）、工具定义、文档加载与切分 |
| **LangGraph** | Supervisor 多 Agent 图（ADR 0023）、子图（入学测是自适应循环子图、出题是 generate → critic 循环子图）、Postgres checkpointer 做会话持久化（长期记忆不用 Store，见 ADR 0009） |
| **OpenTelemetry**（取代原计划的 LangSmith，见 ADR 0005） | 可选的全链路 trace（OpenInference 埋点，OTLP 导出到本地 Phoenix 或任意后端）；用量统计走自建 `llm_usage` 表；评估数据集与回归评测用 pytest |
| **GraphRAG** | 语法知识图谱：真相源是 `grammar.yaml`（前置依赖人工整理，易混关系 LLM 起草 → 人工审核），同步到 Postgres 的 `kc_edges`；检索 = 递归查询前置链和易混点，直接 join 学习者的掌握度和错误证据，用于错因溯源和选题（ADR 0022；以后资料多了再加向量召回） |
| **长期记忆** | 自建表：`user_profile`（结构化画像）+ `memories`（事实记忆和会话摘要，embedding 可选）；回复后由后台反思节点用结构化输出抽取（借鉴 LangMem 的增/改/删思路，不引入该库）；结构化学习者模型放 PG 表（见 ADR 0009、0010） |

---

## 二·五、自适应学习引擎（核心亮点）

**设计原则：LLM 负责“理解和生成”，算法负责“记账和调度”。** 掌握度不能让 LLM 凭感觉打分（不稳定、不可复现），要由可解释的算法根据证据更新；LLM 负责给错误归因、分析根因、生成练习。

### 闭环
```
证据采集 → 学习者模型更新 → 诊断 → 选题规划 → 练习生成 → 校验 → 作答批改 → 回到证据采集
 (所有场景)    (算法)       (LLM+图谱)   (算法)      (LLM)    (LLM 审题)
```
1. **证据采集**：对话、写作、阅读题、背词、口语里出现的每个错误，都由 LLM 用结构化输出打上标签：`{知识点 KC id, 错误类型, 原句, 改正, 严重度, 是否母语迁移}`。KC（knowledge component）= 语法点、单词或技能子项，和语法图谱节点共用 id。
2. **学习者模型（算法）**：每个 KC 维护掌握度 `p_mastery`：语法 KC 用贝叶斯知识追踪 BKT，入学测和技能估计用 Elo 逻辑模型（题目难度用 Elo 按作答校准；入学测里学习者能力每题后对全部作答做最大后验拟合，与作答顺序无关，见 ADR 0010 落地记录），单词直接取 FSRS 的可提取性（读时现算，不存，见 ADR 0010）。**语法 KC 也接入 FSRS**，错误模式像单词一样有“到期复习”。区分两种证据：做题时答对（识别）和自由表达中用对（产出）。后者权重更高，这是“真正学会”的信号。
3. **诊断 Agent（LLM + GraphRAG）**：每次学习结束和每周各跑一次。输入是低掌握度 KC 和错误证据，沿图谱查前置依赖和同类易错点，输出**带证据引用的根因假设**，例如“虚拟语气错 6 次，其中 4 次是 would have done 形式错误 → 根因：完成时掌握度 0.38”。结果写入长期记忆，并展示给用户。
4. **选题规划（算法）**：优先级 = 薄弱度 × 重要度（CEFR 等级、使用频率）× 是否到期。按 **85% 规则**控制难度，让预估正确率保持在 80–85% 左右，也就是“有挑战但做得出来”。
5. **练习生成（LLM）** —— “科学好记、不死板”靠这些学习科学原则落地：
   - **提取练习**（retrieval practice）：主动回忆，而不是重读讲解
   - **交错练习**（interleaving）：薄弱点和已掌握的点混在一起出，不一次只练一个
   - **变式**：同一 KC 轮换题型，包括改自己说过的原句、完形、句型转换、中译英、“找茬”（在新闻段落里找错）、情景小对话、限定语法的微写作
   - **个性化语境**：例句和题目用用户的兴趣、职业和最近读过的新闻来写（记忆里有这些信息）
   - **i+1 输入**：材料只比当前水平高一点点
   - **解释型反馈**：做错后讲“为什么错”并对比正确用法，不只给答案
6. **校验（生成—审查模式）**：LangGraph 里由 critic 节点独立做一遍题，检查答案是否唯一、是否正确、难度是否达标，不通过就重新生成。这是控制 LLM 出题幻觉的关键，也是离线评估集的评估对象。
7. **“学会”的判定**：同一 KC 在 ≥3 种题型中、跨 ≥2 天答对，**并且**在最近的自由对话或写作里没再出现同类错误，才标为已掌握；之后交给 FSRS 做长期维持。

### 单词本：词表做骨架 + LLM 做个性化（混合方案）
- **需要预置词表**，但不照搬墨墨。纯 LLM 定制的问题是：覆盖率没保证（考试/等级词汇会漏）、进度无法量化（“CET6 背了 62%”这种进度感对坚持很重要）、每个词都调 LLM 成本也高。
- **骨架**：ECDICT 开源词库自带考试标签（中考/高考/CET4/CET6/考研/TOEFL/IELTS/GRE）、柯林斯星级和 BNC/COCA 词频。用户按目标选词书，新词出现顺序按词频加用户水平排序。
- **LLM 个性化层**：
  - **自动收词**：阅读里点过的词、对话和写作里用错或不会的词进“我的生词本”，这类词优先级高于词书
  - **跳过已会**：快速“认识/不认识”筛选把熟词直接标为已掌握；入学测按估计的词汇量给出“这些词你大概率认识”，学习者确认后批量标熟（可整批撤销），不浪费时间
  - **例句**：复习卡片先显示 Tatoeba 的真例句（人工翻译，CC BY 2.0 FR，标来源）；没有或想要更多时，学习者点“AI 例句”按需生成（见 ADR 0020）
  - **个性化例句和记忆法**：结合用户兴趣生成例句；词根词缀、搭配、近义辨析、易混词；结果**缓存**，同一个词每个用户只生成一次
  - **从语境中复习**：到期的词尽量出现在当天的阅读材料和对话里，不只是卡片
- **调度**：统一用 FSRS（纯算法，不调用 LLM）。单词和语法 KC 共用一个调度器。

---

## 三、核心数据模型（初稿）

- `tenants`, `tenant_members`, `provider_connections`（加密 key）, `tenant_model_routes`（见 ADR 0004）, `llm_usage`（见 ADR 0005）
- `users`, `user_profile`（母语、目标、目标考试、兴趣、职业、每日时长、讲解语言、CEFR、时区）, `memories`（kind[fact/episode], content, 来源会话, 可选 embedding；见 ADR 0009）
- `skill_estimates`（user, skill[listening/speaking/reading/writing/grammar/vocab], rating, uncertainty, updated_at）, `placement_sessions`（入学测子图的 thread 和状态）
- `learning_advice`（每人一行：看板上的 AI 建议缓存，见 `docs/plans/P1-mvp.md` §7.5）
- `words`（词库：ECDICT 开源词典导入）、`word_sentences`（例句：Tatoeba 英中句对，每词最多 2 句，见 ADR 0020）、`user_cards`（FSRS 状态：stability, difficulty, due, reps, lapses, state）、`review_logs`
- 语法 KC 清单（`grammar.yaml`，ADR 0010）同步到 `kc_edges`（from_kc, to_kc, kind[prerequisite/confusable]，ADR 0022）、`kc_evidence`（source[chat/placement/exercise/writing/reading]，P2 加 format、attempt_id）（所有观测只追加，错误行带 error_type、original、correction、severity；掌握度由它重放得出，见 ADR 0012）
- `agent_activities`（user, conversation, turn_id=学习者消息 id, kind[step/tool/mcp/background], name, call_id, status[ok/failed/skipped], duration_ms, summary JSONB 白名单字段、记忆只存引用；见 ADR 0013）
- `kc_mastery`（user, kc_id, kind[word/grammar/skill], p_mastery, recog_correct, produce_correct, formats_passed, fsrs_state）
- `exercise_sets`（一组练习：kc_plan, status, 来源）、`exercises`（按学习者私有：kc_id, format, content, answer, difficulty, critic JSONB, status[ok/rejected/reported]）、`attempts`（user, exercise_id, response, correct, latency, feedback），见 ADR 0021
- `writing_submissions`（prompt, text, 逐句 corrections, 四维 scores，可选 conversation_id；ADR 0023）
- `diagnoses`（user, period, root_causes JSONB, evidence_refs）
- 词书（按 exam tag 的虚拟分组，定义在代码里，ADR 0011）、`user_word_book`（当前词书、每日新词数、筛选进度）、`word_enrichment_cache`（例句、记忆法）
- `feeds`（内置 + 学习者自加）、`feed_subscriptions`（user, feed, topics）、`articles`（feed, url, 正文, 许可标记）、`article_versions`（租户, 目标等级, 改写正文, 词表, 理解题）、`reading_sessions`（ADR 0024）
- `scheduler_runs`（定时任务上次运行，ADR 0025）、`daily_plans`（user, 日期, items, status）
- `attachments`（conversation, message_id, kind[image/audio/document], mime, data bytea, status, text 派生文本, meta JSONB；见 ADR 0008）；以后做文档 RAG 时加 `attachment_chunks`（pgvector）
- `speaking_sessions`, `pronunciation_scores`
- LangGraph 自带：checkpoints 表、store 表（记忆）

---

## 四、分阶段交付（每阶段结束可用、可演示）

**P0 骨架（约 1 周）**
monorepo（`backend/` uv + FastAPI，`frontend/` Next.js，`docker-compose.yml`）；provider 层 + 配置；多租户凭据（租户自配 key / base_url / 路由）；llm_usage 用量记录 + 可选 OTel tracing；用户注册登录（JWT）；最简对话流式输出。

**P1 MVP：私教对话 + 长期记忆 + 背单词 + 入学测 + 能力看板**（详见 `docs/plans/P1-mvp.md`）
主图加 load_context 与后台反思、记忆读写闭环（可视化“AI 记住了你什么”页面）；FSRS 背单词（ECDICT 导入、词书选择、熟词筛选、复习页）；CEFR 自适应入学测子图；**自适应引擎第一版：错误打标 + kc_mastery 更新**；**agent 活动公示**（每条回复下可展开“私教做了什么”：读取的记忆、调用的工具、回复后记下的内容，见 ADR 0013 和 `docs/agent-tools.md`）；**个人能力看板**（图表 + 嵌入的“今天”私教对话：算法出候选，开口前显示规则问候和快捷回复，私教在对话里给出直达复习、入学测或语法练习的卡片，见 ADR 0016）；**AI 用量标记**（每个会调用模型的入口旁有“AI”标，悬停或点按显示调用了哪些模型任务、每次约多少 token，见 ADR 0014）；**私教工具调用与确认卡**（私教可以提议换词书、设学习目标，并给出练习和直达卡片。有副作用的操作要学习者确认后才执行，执行后可以撤销；入学测结果页内嵌学习规划对话，见 ADR 0015、0016）。**对话的中英比例与单词气泡**（“多说中文 / 多说英文”全局开关，没选过时按等级给默认；私教气泡可切换看中文版 / 英文版；私教气泡里的英文单词悬停或点按弹出单词气泡：音标、释义、朗读、原句、按需 AI 例句、加入生词本；私教气泡可朗读，先用浏览器 `speechSynthesis`，见 ADR 0017）。**朗读的三层方案**（浏览器自己挑好声音、按句切分、学习者可调声音和语速 → 单词发音预生成缓存 → 可选的服务端朗读连接，失败退回浏览器，见 ADR 0018）。

**P2 自适应引擎完整版 + 阅读 + 语法 GraphRAG + 写作**
（详见 `docs/plans/P2-adaptive-reading-writing.md`）顺序：练习引擎 → Supervisor 与写作 → 阅读与定时任务 → 语法图谱与诊断 → 每日计划。选题规划 + 六种题型的练习生成与 critic 校验 + 批改 + 语法点接入 FSRS 与“学会”判定 + 练习页 + 最小评估集（ADR 0021）；LangGraph Supervisor 主图（确定信号优先路由到各 coach，从 P1 移来）+ 写作批改回写学习者模型（ADR 0023）；RSS 抓取（NASA、Global Voices、自加）+ 分级改写 + 理解题 + 自动收词（ADR 0024）；APScheduler 定时任务 + 后台调用每日上限（ADR 0025）；语法知识图谱存 Postgres + 诊断 Agent（ADR 0022）；每日学习计划（复用确认卡，可撤销，ADR 0015）。

**P3 语音（双模式，配置切换）**
- **模式 A · 级联管线**（默认，便宜、完全可控）：ASR → LangGraph（完整记忆/工具/trace）→ TTS。本地用 speaches 容器（faster-whisper，OpenAI 兼容接口，作为租户连接接入，见 ADR 0008），线上 Groq/SiliconFlow；朗读按 ADR 0018 的三层方案（浏览器优先，服务端朗读是租户可选的连接，不内置 edge-tts，不在后端容器里跑朗读模型）。语音消息的转写在 11B 已经实现，P3 在此基础上做朗读、跟读和口语。私教气泡和单词的朗读在 P1 先用浏览器 `speechSynthesis`（ADR 0017），任务 25 按 ADR 0018 改为三层：浏览器挑好声音 → 单词发音预生成 → 可选服务端朗读（provider 层 `tts` 任务，兼容 OpenAI 的 `/audio/speech` 或 Azure 语音），失败时退回浏览器。用于朗读、跟读、半双工口语练习。
- **模式 B · 端到端实时语音**（像 ChatGPT 语音模式：低延迟、可打断、有语气）：`speech.realtime` provider 支持 Gemini Live（有免费档，首选）和 OpenAI gpt-realtime（-mini 更便宜）。浏览器通过 WebRTC/WebSocket 直连厂商，后端只签发临时 token，所以低配服务器也扛得住。
  - 和 Agent 体系的衔接：开会话时把用户画像、CEFR 等级、情景设定注入 system instructions；查词、记生词等能力用 realtime 的 function calling 回调后端；会话结束后，把转写文本送进 LangGraph 的 `reflect_memory` 节点，写回长期记忆和学习者模型。
  - 端到端模型不输出音素级分数，所以发音评测仍然走独立 provider（Azure 免费档）。

**P4 企业级打磨**
评估集（pytest）+ CI 回归评测；用量/成本看板；限流；提示词版本管理；低配服务器部署（compose + 资源限制）；README 架构图与演示脚本。

---

## 五、目录结构（初稿）

```
lingo-agent/
├── backend/
│   ├── app/
│   │   ├── api/            # FastAPI 路由
│   │   ├── agents/         # LangGraph 图：supervisor, 各 coach 子图, assessor
│   │   ├── memory/         # 记忆抽取、读取、学习者模型
│   │   ├── providers/      # llm / embedding / asr / tts / pronunciation
│   │   ├── adaptive/       # 学习者模型(BKT/Elo)、语法图谱查询(graph.py)、诊断、选题规划、练习生成+critic
│   │   ├── services/       # fsrs, cefr, vocab(词书/收词/丰富化), news
│   │   ├── scheduler/      # APScheduler 任务
│   │   └── db/             # SQLAlchemy 模型 + Alembic
│   ├── evals/              # 评估数据集与评估器（pytest）
│   └── tests/
├── frontend/               # Next.js
├── config/                 # providers.dev.yaml / providers.prod.yaml（PROVIDERS_CONFIG 选择，见 ADR 0002）
└── docker-compose.yml      # postgres(pgvector), backend, frontend；redis、phoenix、asr 走 profiles 按需启动
```

---

## 六、风险与取舍

1. **低配服务器**：PG + 后端 + 前端，语法图谱也放 PG（ADR 0022，不再单独跑 Neo4j）；重模型只在 dev 本地跑。
2. **新闻版权**：内置来源只用公有领域和允许改写的 CC BY 内容；全文只存在部署方数据库，始终显示出处、原文链接和许可，不对外公开分发（ADR 0024）。
3. **发音评测**：高质量本地方案（wav2vec2 音素对齐 GOP）工程量大，先用 Azure 免费档，本地方案放到后期。
4. **免费 API 的稳定性**：edge-tts 是非官方接口（因此不内置，见 ADR 0018），Groq/SiliconFlow 免费档有额度限制，所以 provider 层必须支持降级链（fallback）。

## 验证方式（每阶段）
- 自适应引擎：用模拟学习者（固定弱点的 LLM persona）跑多轮，验证系统能识别出预设的弱点、练习集中在这些点上、掌握度曲线随之上升。这也是很好的演示素材。
- 后端：pytest（FSRS 调度、BKT/Elo 更新、选题优先级、CEFR 更新、provider 切换的单测）；LangGraph 图用固定输入跑集成测试。
- 可观测：开启 OTel 后在本地 Phoenix 看 trace，确认路由、记忆读写节点按预期执行；P4 起跑评估集（pytest）并对比分数。
- 端到端：`docker compose up` 后在浏览器走完“注册→入学测→对话（第二次会话能引用第一次的记忆）→背单词→阅读→语音跟读”全流程。
