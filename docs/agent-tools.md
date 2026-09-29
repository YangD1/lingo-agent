# Agent 工具与后台步骤清单

私教 agent 用到的每个工具、MCP 服务和后台步骤都登记在这里（ADR 0013）。**新增或修改时必须同步更新本文件。**

所有模型调用都经过 provider 层，按“模型任务”路由（ADR 0002、0004）；每次调用记录在 `llm_usage`（不含 prompt 和输出内容）。

## LLM 工具调用（模型决定是否调用）

目前没有。P1 的对话是固定流程，模型不能自行调用工具。

## MCP 服务

目前没有。

## 对话流程中的步骤（每轮都执行）

| 步骤 | 代码 | 读 | 写 | 模型任务 | 学习者在哪里能看到 / 撤销 |
|---|---|---|---|---|---|
| 读取学习者上下文 | `agents/chat_graph.py` `load_context` | 画像、事实记忆、相关的会话摘要 | 无（只放进本次 prompt，不进 checkpoint） | `embedding/memory`（有配置时用于检索摘要） | `/memory` 页面查看、修改、删除 |
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
| 反思：记忆与画像 | `memory/reflection.py`、`memory/worker.py` | 本轮及之前几条消息、画像、事实记忆 | `memories`（增删改事实）、`user_profiles`（学习者没手改过的字段） | `llm/reflect`；向量化用 `embedding/memory` | `/memory` 页面 |
| 反思：会话摘要 | 同上 | 新消息、旧摘要 | `memories`（episode） | `llm/reflect` | `/memory` 页面 |
| 反思：语法错误打标（任务 8，开发中） | 同上 | 本轮学习者消息、语法 KC 清单 | `kc_evidence`；由证据重放更新 `kc_mastery` | `llm/reflect` | `/learner` 页面（任务 9） |
