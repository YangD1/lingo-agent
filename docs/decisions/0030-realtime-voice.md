# 0030 · 实时语音：后端中继、OpenAI Realtime 协议优先、限额与工具

- **状态**：已采纳（2026-10-09，任务 52；P3 计划 D3、D4、Q7 由用户确认，全部按推荐）
- **日期**：2026-10-09
- **影响**：**修订 PLAN P3 模式 B 和 ADR 0001** 的“浏览器直连厂商、后端只签发临时 token”，改为后端中继；provider 层新增 `realtime` 一节和两个适配器 `openai_realtime`、`gemini_live`；新增 WebSocket 接口 `/speech/realtime`；`conversations.purpose = realtime`；实时会话的工具在 `docs/agent-tools.md` 登记；租户设置加实时语音时长上限。复用 ADR 0029 的情景、证据和小结。

## 背景
- PLAN 原定：浏览器通过 WebRTC / WebSocket 直连厂商，后端只签发临时 token，低配服务器也扛得住；首选 Gemini Live（有免费档），备选 OpenAI gpt-realtime。
- 核实（2026-10-09，详见 `docs/plans/P3-voice.md` §2.1）：
  - Gemini Live、OpenAI Realtime 都支持浏览器临时 token，但**都不支持大陆访问**（OpenAI 从大陆用有封号风险）。
  - 国内能访问的：阿里 Qwen-Omni-Realtime（OpenAI Realtime 风格事件协议，工具调用、双向转写、单次 120 分钟；临时 key 存在，但鉴权要请求头，浏览器 WebSocket 设不了）、阶跃 StepFun（兼容 OpenAI Realtime，无临时 token，官方示例走服务端中继）、火山豆包（二进制私有协议，无临时 token）。
  - 也就是说，浏览器直连在国内部署时一家都用不了。
- 本项目的约束：工具调用身份要从运行时 context 注入（ADR 0013），用量要进 `llm_usage`，学习者能看到私教做了什么，挂断后要写回记忆和学习者模型。

## 决定

### 1. 连接方式：后端中继（D3）
- 浏览器 ↔ 后端 WebSocket `/speech/realtime`（JWT 鉴权，同现有接口）↔ 厂商。后端只转发音频帧和事件，不解码、不重采样（浏览器按厂商要求的格式采集和播放，比如 PCM16 16kHz 进 / 24kHz 出），所以每个会话的 CPU 和内存很小；任务 60 实测后把数字写进落地记录。
- 后端在中继里做这些事：
  - 开会话时下发 system instructions 和工具定义（浏览器不能改）；
  - 执行工具调用（身份来自会话 context，不来自模型参数）；
  - 收集双方转写；
  - 按厂商返回的 usage 记 `llm_usage`（task `realtime`，音频 token 计入 input / output，另记 `audio_seconds`）；
  - 计时并执行时长上限。
- 浏览器 → 后端的消息只允许白名单类型（音频、打断、结束），其余丢弃，防止前端篡改会话设置。
- 单实例部署（ADR 0025）下长连接没有额外的协调问题；后端重启会断开进行中的通话，前端提示后可以重新接通。
- 直连作为以后的优化保留：OpenAI、Gemini 部署在海外时可以用临时 token 省一跳，接口上留 `transport` 字段，P3 不做。

### 2. 适配器（D4）
- `realtime` 一节，和 `asr` 同样的规则（显式配置、按顺序 fallback 只在接通时生效，通话中途不切换厂商）。
- **`openai_realtime`**（先做）：OpenAI Realtime 事件协议（`session.update`、`input_audio_buffer.append`、`response.*`、`conversation.item.*`、function call / output）。一份代码覆盖 OpenAI、Qwen-Omni、StepFun；各家在 URL、鉴权、模型名、音频格式、转写配置字段上的差异放在适配器的小表里。
- **`gemini_live`**（第二个做）：Gemini Live 的 `BidiGenerateContent` 协议；单连接约 10 分钟要续接，开上下文压缩去掉 15 分钟上限，适配器负责透明续接。
- 后端对前端暴露统一的事件：音频片段、学习者 / 私教字幕（增量与定稿）、打断、工具活动、剩余时间、结束原因。前端不关心是哪家厂商。

### 3. 会话上下文
- 开会话时后端拼 system instructions（`prompts/realtime_tutor.md`）：画像、CEFR 等级、中英比例、相关记忆、情景（ADR 0029 §1）、口语回复约束和纠错方式（ADR 0029 §2，recast）。
- 记忆和学习者模型只在开场注入一次，通话中不再检索。

### 4. 工具（ADR 0013）
- 首批：`lookup_word`（只读，查词库）、`add_to_vocab`（幂等：同一个词再加不重复；可撤销：通话结束页列出本次加的词，可以一键移除）、`end_session`（私教判断对话自然结束时提议挂断，前端确认）。
- 工具失败作为工具结果返回模型，不中断通话；每轮工具调用次数有上限；工具结果是不可信数据。
- 每次工具调用推一条工具活动给前端，通话结束后写入 `agent_activities`，和普通对话一样能展开看。

### 5. 限额（Q7）
- 单次通话上限默认 15 分钟，每人每日默认 30 分钟（按 UTC 切天，同 ADR 0025 的简化），租户 owner / admin 可改，0 表示关闭实时语音。
- 结束前 1 分钟提示；到点后让私教说一句收尾再挂断（发一条结束指令，最多再等 10 秒）。
- 实时语音是学习者当下发起的调用，不占后台每日 token 上限。

### 6. 挂断之后
- 双方定稿的转写按顺序存成一次对话（`conversations.purpose = realtime`，`scenario_id` 同 ADR 0029），消息带“语音通话”标记。
- 交给反思：记忆抽取、错误打标（`source = speaking`，按 ADR 0029 §4 过滤转写不可靠的话语）。
- 生成同 ADR 0029 §5 的口语小结，`speaking_sessions.mode = realtime`。

### 7. 公示（ADR 0014）
- `features.yaml`：`realtime_call`（task `realtime`，按分钟估算；说明里写清楚和级联模式的成本差别），接通按钮挂 `AiBadge`；挂断后的反思和小结按已有登记。
- 通话中界面显示工具活动；`docs/agent-tools.md` 加“实时语音通话”一节（工具、上下文里注入了什么、转写如何保存）。

## 取舍
- **中继而不是直连**：直连省一跳延迟和服务器长连接，但国内一家都用不了，而且工具调用、用量、限额、转写都得让浏览器转手，前端可以篡改。中继多出的延迟在同区域部署时是几十毫秒，相对实时语音几百毫秒的首包延迟可以接受。资源占用待任务 60 实测，如果超出低配服务器的承受范围，再回到这里修订。
- **先 OpenAI 协议，后 Gemini**：OpenAI 协议一份代码覆盖国内外三家；Gemini 有免费档但国内不可用，作为第二个适配器。
- **通话中不切换厂商**：中途切换会丢上下文和音色，体验更差；接通失败时才按路由顺序换下一家。
- **开场注入一次上下文**：通话中做检索会增加延迟和复杂度；需要的信息（查词）走工具。

## 落地记录（任务 60，2026-10-11）
- **已做**：`realtime` 路由节和厂商小表（60.1）、`openai_realtime` 适配器（60.2，正式版 / beta 两种写法）、`WS /speech/realtime` 中继（60.3）、开场上下文（60.4）、限额（60.5）、公示与连接测试（60.6）。工具、挂断后转写 / 反思 / 小结、`gemini_live` 在任务 61，通话界面在 62。
- **§1 鉴权**：浏览器 WebSocket 设不了请求头，用登录 cookie（也收 Bearer），并要求 Origin 等于 Host 或 X-Forwarded-Host，防跨站 WebSocket 劫持。Next 开发服务器的 `/api` 代理能转 WebSocket（2026-10-10 实测），standalone 构建到 62 / 64 在 Docker 上再验。
- **§1 用量**：厂商每次回答记一条 `llm_usage`（task `realtime`），音频 token 计入 input / output，`audio_seconds` 记的是这一轮学习者音频的秒数。
- **§5 限额补充**：同一学习者同时只能打一通（`realtime_busy`）。原方案没有这条；不加的话，并行开几通，每通都能拿到当天全部剩余分钟。通话时长每 15 秒写一次，后端重启断掉的通话也计入当天分钟。
- **§7 公示**：`realtime_call` 按每分钟估算（`features.yaml` 的 `per: minute`，只用于 `realtime` 一节）：有历史时取最近 20 通已挂断、超过 30 秒的通话，把用量加起来除以通话分钟数；没有历史时默认每分钟 20,000 输入 + 1,000 输出 token。选了情景时接通前还有一次 `memory` 向量化，一起登记。连接测试只发会话设置、收到 `session.updated` 就挂断，不让模型说话，所以不产生音频 token。
- **资源实测（Q60i，`backend/scripts/realtime_load.py`）**：单个 uvicorn 进程、临时数据库，假厂商 10 路并发通话 60 秒，双向一直有音频（每路每秒 10 帧 PCM16 24kHz，每个方向约 47KB/s，厂商侧 base64 JSON；真实通话双方轮流说，比这低），厂商每 5 秒报一次用量。结果：常驻内存空闲 217.8MB → 峰值 219.5MB（10 路共约 +2MB，每路不到 0.5MB）；CPU 平均为单核的 2.3%；12,000 帧全部转发，12 通全部正常挂断并写了用量。测试机是 i9-13900HX，低配服务器单核慢几倍也只是个位数到十几个百分点。结论：中继的内存和 CPU 都不是瓶颈，§1 的中继方案不需要修订；带宽是每路每个方向约 50KB/s（base64 后约 64KB/s），部署时要看服务器出口带宽。
