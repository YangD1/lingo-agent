# P3 语音 · 详细实施计划

> 状态：**已确认**（2026-10-09 起草，同日用户确认 D1–D6、Q1–Q8 全部按推荐，见 §9），按 §8 的顺序执行。
> 上位设计见 `docs/PLAN.md` 第四节 P3、ADR 0008（语音转写）、ADR 0018（朗读三层）。本文件只写 P3 范围内“怎么做”。
> 相关 ADR：已有 0002 / 0004 provider 层、0008 多模态与转写、0013 工具与公示、0014 AI 用量公示、0018 朗读三层、0023 Supervisor 与 coach、0025 后台上限；P3 新增 0028–0030（任务 52）。

## 0. P3 的完成定义（Demo 脚本）

在 P2 Demo 的基础上：

1. **朗读更好听**：租户在设置页加一个朗读连接（Azure 语音、兼容 OpenAI `/audio/speech` 的服务，或本地 speaches 容器里的 Kokoro）后，私教气泡、单词气泡、背单词页的朗读改由服务端生成，声音统一；同一句第二次读走缓存、不再计费。连接出错时自动退回浏览器朗读，不打断学习者。
2. **单词发音预生成**：部署方在设置页对当前词书一键预生成单词发音（先显示词数、字符数和估算费用），后台断点续跑；查词朗读优先用缓存。
3. **跟读**：在私教回复、阅读文章、单词例句旁点“跟读”，先听示范，再录自己读一遍，看到整体分（准确度、流利度、完整度，美音时有韵律）和逐词标注，点开一个词能看到哪个音素读错；读错的词可以一键加入生词本。没配发音评测时，用语音转写对比给出“哪些词没读出来 / 读成了别的词”的粗反馈，并说明这是粗略结果。
4. **口语练习（级联）**：选一个情景（面试、点餐、问路、开会……按等级给），按住说话 → 转写 → 私教（speaking_coach）按情景回应 → 自动朗读回复。结束时看到这次的口语小结：说错的地方、更地道的说法；错误作为“产出”证据进入学习者模型，口语能力估计更新。
5. **实时语音对话**：配置了实时语音连接后，可以像打电话一样和私教聊：低延迟、可以打断、有字幕。私教开场就知道学习者的等级、目标、记忆和情景；聊天中能查词、记生词（工具调用，界面上看得到）；挂断后转写文本进入反思，写回长期记忆和学习者模型。有单次时长和每日分钟上限。
6. **背单词听音 / 拼写**：复习卡片可切到“听音辨词”和“拼写”两种题型（朗读走上面的三层）。
7. 所有新的模型调用都在 `features.yaml` 登记、入口挂 `AiBadge`、在 `docs/agent-tools.md` 公示；录音默认不保存（Q3）。
8. `make test`、`make lint`、`make e2e` 全绿；GitHub Actions 全绿；E2E 用假的朗读、评测和实时服务，不调真实 API。

**P3 不做**：本地发音评测模型（wav2vec2 音素对齐，PLAN 风险 3，后置）、视频、多人语音、电话接入、自训练声音。

---

## 1. 范围与子阶段

| 子阶段 | 内容 | 依赖 | 对应 Demo |
|---|---|---|---|
| **P3a** 朗读第 2、3 层 | provider 层 `tts` 段、Azure 与兼容 OpenAI 两种适配、音频缓存、前端优先服务端朗读并退回浏览器、单词发音预生成（原 25.4、25.5） | ADR 0018 | 1、2 |
| **P3b** 跟读与发音评测 | provider 层 `pronunciation` 段（Azure）、转写对比兜底、评分表与证据回写、跟读组件 | P3a 的示范音频 | 3 |
| **P3c** 级联口语练习 | speaking_coach、情景清单、半双工语音界面、口语证据回写、口语小结 | P3a、已有的 ASR | 4 |
| **P3d** 实时语音 | provider 层 `realtime` 段、连接方式（D3）、会话上下文注入、工具调用、挂断后反思、时长上限 | P3c 的情景与证据 | 5 |
| **P3e** 背词听音 / 拼写 | 复习卡片两种新题型（P2 移过来的积压项） | P3a | 6 |
| **P3f** 收尾 | P3 全链路 E2E、真模型冒烟、README、Docker、`make ci` | 全部 | 7、8 |

---

## 2. 厂商现状（2026-10-09 核实，开工前每项再核一次）

### 2.1 实时语音（模式 B）

| 厂商 | 模型 | 浏览器直连 | 工具调用 / 双向字幕 | 单次会话 | 价格 | 大陆访问 |
|---|---|---|---|---|---|---|
| Google Gemini Live | `gemini-3.8-live` | 临时 token（预览版，v1beta，WebSocket；默认 30 分钟有效、1 分钟内开会话、用 1 次，可在服务端锁定模型和 system instructions） | 支持 / 支持 | 纯音频 15 分钟，开上下文压缩后不限；单连接约 10 分钟，要续接 | 有免费档（数据会被用于改进产品，数字限额只在 AI Studio 看）；付费约输入 $0.005/分钟、输出 $0.018/分钟 | **不支持** |
| OpenAI Realtime | `gpt-realtime-2.1`、`-mini` | 临时密钥 `POST /v1/realtime/client_secrets` + WebRTC | 支持 / 支持 | 60 分钟 | mini：音频输入 $10、输出 $20 每百万 token | **不支持**（有封号风险） |
| 阿里 Qwen-Omni-Realtime | `qwen3.8-omni-flash-realtime` 等 | 临时 key（`st-`，1–1800 秒）存在，但文档里的鉴权是请求头，浏览器 WebSocket 设不了；WebRTC 未验证 | 支持 / 支持 | 120 分钟 | 未核实 | 可以 |
| 阶跃 StepFun | `stepaudio-2.5-realtime` | 无临时 token，官方示例走服务端中继 | 协议兼容 OpenAI | — | $1.5 / $10 每百万 token；3 代预览版暂时免费（未核实） | 可以 |
| 火山豆包 | 端到端实时语音 | 无，二进制私有协议 | — | — | 输入 ¥80 每百万 token | 可以 |

要点：**事件协议上 OpenAI、Qwen-Omni、StepFun 基本一致**（OpenAI Realtime 风格），一个适配器能覆盖三家；Gemini 是另一套。**国内能访问的几家都没有可用于浏览器的临时 token**，所以 PLAN 原定的“浏览器直连、后端只签 token”在国内部署不成立，见 D3。

### 2.2 发音评测

| 方案 | 能力 | 免费额度 | 备注 |
|---|---|---|---|
| Azure 发音评测 | 音素 / 音节 / 词 / 全文；准确度、流利度、完整度；韵律只有 en-US；有参考文本（跟读）和无参考文本两种 | F0 每月 5 小时（和语音转写共用），并发 1 | S0 按语音转写价计费，韵律另加；后端用 REST 短音频接口（≤ 30 秒）或浏览器用 10 分钟的授权 token + JS SDK；en-GB 支持情况和大陆访问未核实 |
| 讯飞 ISE | 音素级 | 每天 500 次，实名后再送 1 万次 | 国内可用；WebSocket 私有协议 |
| 腾讯智聆口语评测 | 音素级 | 无长期免费；¥9.9 / 1 万次起 | 国内可用 |
| SpeechSuper | 音素级 | 试用要找销售 | 月最低消费 $20 |

### 2.3 服务端朗读

- Azure 神经语音：F0 每月 50 万字符免费，每分钟 20 次请求；S0 $15 / 百万字符。和发音评测**可以共用同一个 Azure 语音连接**。
- OpenAI `gpt-4o-mini-tts`：文本输入 $0.60、音频输出 $12 每百万 token。
- 硅基流动 `/v1/audio/speech`：按字节计费，约 ¥50 / 百万字节（具体模型对应关系未核实）。
- 自部署：**speaches 已经支持 Kokoro 和 Piper 朗读**（兼容 OpenAI `/v1/audio/speech`，按需加载模型），仓库里的 `make asr-up` 用的就是 speaches。Kokoro-82M 权重 Apache-2.0、约 327MB，4 核 CPU 上大约 2 倍实时；内存峰值没有公开数字，要实测。MeloTTS（MIT）、Piper（已改为 GPL-3.0 的 piper1-gpl）作为备选。

来源：Gemini `ai.google.dev/gemini-api/docs/{live,live-session,ephemeral-tokens,pricing,available-regions}`；OpenAI `developers.openai.com/api/docs/{pricing,guides/realtime-webrtc,supported-countries}`；Qwen `help.aliyun.com/zh/model-studio/realtime`；StepFun `platform.stepfun.com/docs/zh/api-reference/realtime/chat`；Azure `learn.microsoft.com/azure/ai-services/speech-service/how-to-pronunciation-assessment`、`azure.microsoft.com/pricing/details/speech/`；讯飞 `xfyun.cn/doc/Ise/IseAPI.html`；腾讯 `cloud.tencent.com/document/product/1774/107342`；speaches `github.com/speaches-ai/speaches`；Kokoro-FastAPI `github.com/remsky/Kokoro-FastAPI`。

---

## 3. 朗读第 2、3 层（P3a，按 ADR 0018 §3–§4）

- **provider**：`config/providers.*.yaml` 加 `tts` 段（和 `asr` 一样走租户连接、按顺序 fallback，只用显式配置的模型，不自动兜底到别的段）。两种适配：
  - `openai_compatible`：`POST /audio/speech`（OpenAI、硅基流动、speaches / Kokoro）。
  - `azure_speech`：新的连接类型（区域 + key），REST + SSML。同一个连接以后给发音评测用（D2）。
- **声音**：路由里每个模型可配美音 / 英音 / 中文声音名；学习者的口音设置（ADR 0018 §2，存在浏览器）随请求传给后端。
- **缓存**：`tts_audio` 表（租户、内容哈希 = 文本 + 声音 + 语速 + 模型、格式、字节、最后使用时间），`bytea` 存储，租户总量上限（默认 200MB）按最久未用淘汰。缓存命中不计 `llm_usage`。
- **接口**：`POST /speech/tts`（文本 ≤ 1000 字符，返回音频或 404 表示没配）；限流复用现有机制。
- **前端**：`lib/speech.ts` 的 `speak()` 先问后端；没配、超时（默认 4 秒出首字节）或失败时退回浏览器朗读，本页记住“服务端不可用”避免每句都等。服务端音频也按句切，逐句播放，可停止。
- **单词发音预生成**：部署方（租户管理员）在设置页对一本词书发起，后台任务分批生成、可断点续跑，显示进度、词数、字符数和按连接单价估算的费用；计入 ADR 0025 的后台每日上限之外的单独额度（Q7）。单词气泡和背单词页优先用缓存。
- **公示**：`features.yaml` 加 `read_aloud`（`tts`，按字符估算）、`word_audio_prefetch`；朗读按钮挂 `AiBadge`（只在配了连接时显示）；`docs/agent-tools.md` 补“对话之外的调用”和后台任务。

- **落地（任务 53、54，2026-10-09）**：后端和前端已完成，细节和与本节的差异见 ADR 0028 落地记录。任务 54 按 Q54a–c 加了：学习者可在自己的浏览器里关掉服务端朗读；设置页按模型和语言选声音；朗读缓存记下触发的学习者，本人可清除、30 天没人播自动删除。
- **落地（任务 55，2026-10-10）**：单词发音预生成按 Q55a–g 完成：设置页“单词发音”估算 → 确认 → 后台分批生成（重启后接着跑）；单词按语速 1 合成、浏览器调速播放；换声音后旧音频可删；细节见 ADR 0028 落地记录。

## 4. 跟读与发音评测（P3b）

- **provider**：`pronunciation` 段，第一个适配器 Azure（后端 REST 短音频接口，有参考文本，粒度到音素，en-US 时开韵律）。浏览器录音（复用 `use-recorder.ts` 的格式和静音拦截）→ 上传后端 → 调评测。Azure 短音频接口不收 webm，后端又没有 ffmpeg / PyAV（不为此加重依赖），所以跟读录音由浏览器直接编码成 16kHz 单声道 WAV（Web Audio，≤ 30 秒约 1MB）。不把 Azure key 或 token 交给浏览器。
- **兜底**（没配发音评测时，D2）：用已有的 `asr` 转写，和参考文本做词级对齐（编辑距离），标出漏读、读成别的词、多读；界面明确写“粗略结果，不是发音打分”。
- **数据**：`pronunciation_attempts`（user、来源 [chat / reading / vocab / speaking]、来源 id、参考文本、提供方、整体分 JSONB、逐词 / 音素结果 JSONB、时长、创建时间）。录音不保存（Q3）。
- **证据**：整体分更新 `skill_estimates.speaking`（Elo，按句子难度）；准确度低于阈值的词记一条单词证据（发音），供背词页标出“这个词你读不准”。不给语法 KC 记证据。阈值放 `rules.yaml`。
- **界面**：`ShadowingPanel` 组件（示范 → 录音 → 结果：整体分环、逐词着色、点词看音素、再听示范 / 再读一次 / 加入生词本），挂在私教气泡、阅读文章段落、单词例句旁。
- **公示**：`features.yaml` 加 `shadowing`（`pronunciation` 或 `asr`，按音频秒数估算）；入口挂 `AiBadge`。
- **落地（任务 56，2026-10-10）**：后端和设置页按 Q56a–f 完成：`pronunciation` 路由节与 Azure 适配器、转写对比兜底、`pronunciation_attempts` 与 `word_pronunciations`、口语能力 Elo、`/speech/shadowing` 接口与记录删除、背词卡片“读不准”；`features.yaml` 拆成 `shadowing` / `shadowing_rough`。英音没有音素名和韵律分（Azure 限制）。细节见 ADR 0028 落地记录；跟读组件在任务 57。
- **落地（任务 57，2026-10-10）**：按 Q57a–g 完成跟读组件：浏览器 AudioWorklet 录音编码成 16kHz WAV、`ShadowingPanel`、挂到私教回复 / 阅读段落 / 复习例句、复习卡片“读不准”、学习者模型页跟读记录；E2E 用假 Azure 评测和假麦克风。细节见 ADR 0028 落地记录。

## 5. 级联口语练习（P3c）

- **情景**：`backend/app/speaking/scenarios.yaml`（id、标题中英、等级范围、角色、目标、开场白要点、可选目标表达），首批 8–10 个（自我介绍 / 面试、点餐、问路、酒店入住、看病、开会发言、电话预约、闲聊兴趣），可以“自由聊”。
- **图**：`speaking_coach` 子图，Supervisor 按会话类型（`conversations.purpose = speaking` + 新列 `scenario_id`）确定路由，不调分类（ADR 0023）。回复要短（口语节奏，`rules.yaml` 限长度）、按等级调难度、不在每轮纠错，只在说错影响理解时自然复述正确说法（recast）；纠错集中在结束小结。
- **语音回合**：按住说话（或点一下开始、再点结束）→ 现有转写 → 正常走对话流式 → 回复按句流式朗读（P3a 的三层）。可以随时切换打字。
- **证据**：转写的学习者话语照常走反思打标，source 记为 `speaking`（`kc_evidence` 约束加一项），算“产出”证据；转写不可靠的词不计（Q5）。
- **小结**：结束时一次结构化调用 `speaking_summary`：说得好的、错误与改法、更地道的说法、下次可练的表达；存 `speaking_sessions`（user、conversation、scenario、开始 / 结束、轮数、说话秒数、summary JSONB）。小结里的表达可一键加入生词本，句子可一键跟读。
- **入口**：新页面 `/speaking`（情景列表 + 历史小结）；看板“今天”私教可给口语卡片；每日计划加可选的“口语 10 分钟”（ADR 0027 的 choice 扩展，Q6）。

## 6. 实时语音（P3d）

- **连接方式（D3，推荐后端中继）**：浏览器 ↔ 后端 WebSocket ↔ 厂商。后端只转发音频帧和事件，不做编解码，单个会话占用很小（任务 60 实测内存和 CPU，写进 ADR）。这样：
  - 国内能用的厂商（Qwen-Omni、StepFun）没有浏览器临时 token 也能接；
  - 工具调用在后端执行，身份从会话 context 注入（ADR 0013），不用浏览器转手；
  - 转写、用量（`llm_usage` 记音频 token）、时长上限都在后端掌握，挂断后直接交给反思。
  - 代价：多一跳延迟（同区域部署约几十毫秒）、后端要保持长连接。直连作为以后的优化（OpenAI、Gemini 支持临时 token），接口上预留。
- **provider**：`realtime` 段，适配器两个：`openai_realtime`（OpenAI、Qwen-Omni、StepFun 共用的 OpenAI Realtime 事件协议，各家差异在适配器里处理）和 `gemini_live`（D4 决定先后）。
- **上下文**：开会话时由后端拼 system instructions：画像、等级、中英比例、相关记忆、情景（复用 P3c 的情景）、回复长度约束；提示词放 `prompts/realtime_tutor.md`。
- **工具**：首批只读和低风险的：`lookup_word`、`add_to_vocab`（幂等、可撤销，ADR 0013）、`end_session`。工具结果作为不可信数据回给模型；界面上显示“私教做了什么”。
- **限额**：单次会话上限（默认 15 分钟）和每人每日分钟上限（默认 30 分钟），租户可改；到时间前 1 分钟提示，到点优雅结束。
- **挂断后**：把双方转写存成一次对话（`conversations.purpose = realtime`），进入反思（记忆、证据，source `speaking`），再生成同 P3c 的口语小结。
- **界面**：通话页（大按钮接通 / 挂断、静音、音量电平、双方实时字幕、工具活动、剩余时间），从 `/speaking` 的情景卡片或看板进入；没配实时连接时只显示级联模式。
- **公示**：`features.yaml` 加 `realtime_call`（按分钟估算，写清楚比级联贵多少）；接通按钮挂 `AiBadge`；`docs/agent-tools.md` 加实时会话的工具。

## 7. 背词听音 / 拼写（P3e）

- 复习卡片新增两种正面：听音辨词（播放发音，四选一释义）、拼写（播放发音 + 释义，输入单词）。评分仍由学习者自评，拼写题由代码先判对错再给默认评分（Q8）。
- 发音走 P3a（缓存 → 服务端 → 浏览器）。没有任何朗读手段时不出这两种题型。

---

## 8. 任务顺序

每项完成标准：测试通过、lint 干净、看板已更新；涉及模型调用的同步 `features.yaml`、`AiBadge`、`docs/agent-tools.md`。外部服务一律用假服务测试，不调真实 API。

| # | 任务 | 验证 |
|---|---|---|
| 52 | ADR 0028 服务端朗读与发音评测的 provider（`tts`、`pronunciation`、Azure 语音连接）、0029 口语练习（情景、speaking_coach、证据）、0030 实时语音（连接方式、适配器、限额、工具）；PLAN 同步（架构图、provider 配置示例、数据模型、P3 段）；ADR 0018 标注第 2、3 层落地 | 人工 review |
| **P3a** | | |
| 53 | `tts` provider（两种适配）+ Azure 语音连接类型 + `tts_audio` 缓存表 + `/speech/tts` + 用量登记；dev 实测 speaches/Kokoro 内存 | 单测 + 假服务集成测试 |
| 54 | 前端朗读优先服务端、退回浏览器；设置页朗读连接测试；`AiBadge` | Vitest + E2E |
| 55 | 单词发音预生成（后台、断点续跑、进度与费用估算）+ 查词优先用缓存 | 集成测试 + E2E |
| **P3b** | | |
| 56 | `pronunciation` provider（Azure）+ 转写对比兜底 + `pronunciation_attempts` + 证据回写 | 单测 + 集成测试 |
| 57 | 跟读组件，挂到私教气泡、阅读、单词例句 | Vitest + E2E |
| **P3c** | | |
| 58 | 情景清单 + speaking_coach 子图 + 路由 + `speaking_sessions` + 证据 source `speaking` + 口语小结 | mock LLM 图测试 + 集成测试 |
| 59 | `/speaking` 页、半双工语音回合、流式朗读、小结页、看板与每日计划入口 | Vitest + E2E |
| **P3d** | | |
| 60 | `realtime` provider + 后端中继 + `openai_realtime` 适配器 + 上下文注入 + 限额 + 用量；实测中继的内存和 CPU | 假实时服务集成测试 |
| 61 | 实时会话工具 + 挂断后转写入库、反思、小结 + `gemini_live` 适配器（按 D4） | 集成测试 |
| 62 | 通话界面 | Vitest + E2E（假实时服务） |
| **P3e** | | |
| 63 | 复习卡片听音辨词 / 拼写 | Vitest + E2E |
| **P3f** | | |
| 64 | P3 全链路 E2E、真模型冒烟（朗读、评测、实时各一家）、README 中英、Docker 重建、`make ci`、推送 | CI 全绿 |

---

## 9. 决定（2026-10-09 用户确认，全部按推荐）

**大方向（D）**

- **D1 子阶段顺序**：推荐 朗读 → 跟读 → 级联口语 → 实时 → 背词听音 / 拼写 → 收尾。理由：朗读是跟读示范和口语回复的基础；级联口语把情景、证据、小结做出来后，实时语音直接复用；实时最贵、外部依赖最多，放后面。备选：背词听音 / 拼写只依赖朗读，也可以紧跟 P3a 先做。
- **D2 发音评测**：推荐先接 Azure（功能最全、免费档每月 5 小时，和朗读共用一个连接），没配时用转写对比兜底；接口按 provider 设计，讯飞 ISE（国内可用、每天 500 次免费）作为第二个适配器放到 P3 之后视需要再做。备选：一开始就同时做讯飞。
- **D3 实时语音的连接方式**：推荐**后端中继**（改 PLAN 原定的“浏览器直连、后端只签 token”）。原因：国内能访问的厂商都没有浏览器可用的临时 token；中继让工具调用、用量、时长上限、挂断后反思都在后端完成。代价是多一跳延迟和长连接，任务 60 实测资源占用。备选：保留直连，只支持 OpenAI 和 Gemini（国内部署用不了实时模式）。
- **D4 实时语音首批厂商**：推荐先做 OpenAI Realtime 协议适配器（一份代码覆盖 OpenAI、Qwen-Omni、StepFun，国内外都有可用的），Gemini Live 第二个做（有免费档，但国内不可用）。真模型冒烟用 Qwen-Omni 或 OpenAI，看你手上有哪家的测试 key。
- **D5 服务端朗读首批**：推荐兼容 OpenAI `/audio/speech`（覆盖 OpenAI、硅基流动、本地 speaches）+ Azure 语音（免费档每月 50 万字符）两种都做。
- **D6 本地朗读模型**：推荐直接用现有 speaches 容器里的 Kokoro（不加新容器，`make asr-up` 一起起），实测内存后写进文档；PLAN / 看板里原来的 MeloTTS 候选不再做。线上仍然不在后端容器里跑模型（ADR 0018）。

**细节（Q）**

- **Q1 跟读句子来源**：推荐私教回复（按句选）、阅读文章段落、单词例句三处；口语小结里的“更地道说法”也能跟读。
- **Q2 发音证据**：推荐整体分更新口语能力（Elo），低分词记单词发音证据并在背词页标出；不影响语法掌握度。
- **Q3 录音保存**：推荐不保存录音（只存分数和转写），隐私最省心；以后要“回听自己的录音”再加，并让学习者可删。
- **Q4 口语练习纠错方式**：推荐对话中只用复述（recast）自然纠正、不打断，错误集中在结束小结里讲。
- **Q5 转写不可靠时的证据**：推荐 ASR 置信度低或文本很短（< 3 个词）的话语不记错误证据，避免把转写错误算成学习者的错。
- **Q6 每日计划加口语**：推荐加可选项“口语 10 分钟”，默认不勾，学习者在确认卡上自己加。
- **Q7 实时语音和预生成的额度**：推荐实时语音按分钟计（单次 15 分钟、每人每日 30 分钟，租户可改）；单词发音预生成是部署方手动发起的，单独确认费用，不占 ADR 0025 的后台每日 token 上限。
- **Q8 拼写题评分**：推荐代码判对错后给默认评分（错 → Again，对 → Good），学习者可以改。
