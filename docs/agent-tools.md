# Agent 工具与后台步骤清单

私教 agent 用到的每个工具、MCP 服务和后台步骤都登记在这里（ADR 0013）。**新增或修改时必须同步更新本文件。**

所有模型调用都经过 provider 层，按“模型任务”路由（ADR 0002、0004）；每次调用记录在 `llm_usage`（不含 prompt 和输出内容）。

## 活动记录（学习者看到的“私教做了什么”）

下面每个步骤跑完都在 `agent_activities` 记一行（`app/activity/service.py` 的 `STEPS` 登记了步骤名、类型和可公示的摘要字段），在每条私教回复下显示：默认收起成一行，点开看明细；设置 →“显示”可以在本浏览器隐藏（只影响显示）。

- **一轮**以学习者那条消息的 id 为键。对话中的步骤通过 SSE `activity` 事件实时推送；回复后的后台步骤由前端在 60 秒内轮询 `GET /conversations/{id}/activity?turn=…`。
- **摘要只含白名单字段**：数量、记忆 id、语法点 id、错误类型和严重度、学习者自己的原话和改正。不含 prompt、模型原始输出、错误原文；失败只记 `failed`，没配模型记 `skipped`。
- **记忆只存引用**：展示时取记忆的当前内容，学习者删掉的显示“已删除”，活动里不留副本。删除会话时它的活动一起删除。

| 步骤名 | 类型 | 摘要字段 |
|---|---|---|
| `load_context` | step | `facts`、`episodes`（真正放进 prompt 的记忆 id）、`profile_items`（画像项数） |
| `reflect_memory` | background | `added`、`updated`（记忆 id）、`deleted`（只计数）、`profile_fields`；挂在一批反思的最后一条学习者消息上 |
| `grammar_tagging` | background | `mistakes`（`kc_id`、`error_type`、`severity`、`original`、`correction`）、`used_correctly`（KC id）；每条学习者消息一行。摘要里有错误原句的副本，所以学习者在 `/learner` 删掉一条证据时，这里对应的一项也去掉；“删除所有学习记录”时这些行全部删除 |
| `vocab_collect` | background | `added`、`existing`（`word_id` + 拼写：新收进生词本的词、已有卡片没有改动的词）；挂在提问的那条学习者消息上，没有收到词的消息不记。接口另返回 `words_on_list`（仍在生词本里的收词），明细据此显示“已移出” |
| `summarize` | background | `episode_id` |

新增工具时在 `STEPS` 登记，类型用 `tool` 或 `mcp`，同一轮多次调用用 `call_id` 区分。

## 学习者在对话里的操作（不经过模型）

| 操作 | 代码 | 写 | 学习者在哪里能看到 / 撤销 |
|---|---|---|---|
| 选中私教回复里的单词加入生词本 | 前端 `components/chat/select-to-add.tsx` → `POST /vocab/mine` | `user_cards`（`source=manual`，规则同生词本页：精确 → 忽略大小写 → 还原原形；已标“认识”的词变回待学） | 选区下方提示结果；`/vocab/mine` 可删除 |

## LLM 工具调用（模型决定是否调用）

目前没有。P1 的对话是固定流程，模型不能自行调用工具。

## MCP 服务

目前没有。

## 对话流程中的步骤（每轮都执行）

| 步骤 | 代码 | 读 | 写 | 模型任务 | 学习者在哪里能看到 / 撤销 |
|---|---|---|---|---|---|
| 读取学习者上下文 | `agents/chat_graph.py` `load_context` | 画像、事实记忆、相关的会话摘要 | 无（只放进本次 prompt，不进 checkpoint）；活动 `load_context` | `embedding/memory`（有配置时用于检索摘要） | 回复下“私教做了什么”；`/memory` 页面查看、修改、删除 |
| 私教回复 | `agents/chat_graph.py` `tutor` | 对话历史、学习者上下文、本轮附件 | checkpoint（对话历史） | `llm/chat`；带图片时 `llm/vision` | 对话页；删除会话即删除 |

## 附件处理（上传后执行）

| 步骤 | 代码 | 读 | 写 | 模型任务 | 学习者在哪里能看到 / 撤销 |
|---|---|---|---|---|---|
| 图片识别 | `attachments/reading.py` | 图片 | 附件的识别文本 | `llm/vision` | 附件卡片里查看、修改识别结果 |
| 语音转写 | `attachments/handlers.py` | 音频 | 附件的转写文本 | `asr` | 同上 |
| 文档解析（扫描页识别） | `attachments/handlers.py`、`documents.py` | PDF / DOCX | 附件的文本 | 扫描页用 `llm/vision` | 同上 |

## 回复后的后台步骤（异步，不阻塞回复）

| 步骤 | 代码 | 读 | 写 | 模型任务 | 学习者在哪里能看到 / 撤销 |
|---|---|---|---|---|---|
| 反思：记忆与画像 | `memory/reflection.py`、`memory/worker.py` | 本轮及之前几条消息、画像、事实记忆 | `memories`（增删改事实）、`user_profiles`（学习者没手改过的字段）；活动 `reflect_memory` | `llm/reflect`；向量化用 `embedding/memory` | 回复下“私教做了什么”；`/memory` 页面 |
| 反思：会话摘要 | 同上 | 新消息、旧摘要 | `memories`（episode）；活动 `summarize` | `llm/reflect` | 回复下“私教做了什么”；`/memory` 页面 |
| 反思：自动收词（与记忆同一次调用） | 同上 + `services/vocab/mine.py` `collect` | 反思给出的候选词（带消息短 id）、`words` | `user_cards`（只为还没有卡片的词建 `source=auto` 的卡，已有卡片一律不动，所以移出就是精确撤销；每次反思最多 5 个，查不到的词丢弃）；活动 `vocab_collect` | `llm/reflect` | 回复下“私教做了什么”：每个词可“移出”；`/vocab/mine`：来源显示“对话中收集”，可删除 |
| 反思：语法打标（与记忆同一次调用） | 同上 + `adaptive/evidence.py`、`adaptive/mastery.py` | 本轮学习者消息（短 id u1、u2）、语法 KC 清单（system prompt 固定前缀） | `kc_evidence`（同一条消息的证据先删后写）；由证据重放更新 `kc_mastery`；活动 `grammar_tagging` | `llm/reflect` | 回复下“私教做了什么”（语法点链到 `/learner?kc=`）；`/learner` 页面：每条证据可查看、可删除 |
