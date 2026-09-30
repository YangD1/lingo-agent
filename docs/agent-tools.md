# Agent 工具与后台步骤清单

私教 agent 用到的每个工具、MCP 服务和后台步骤都登记在这里（ADR 0013）。**新增或修改时必须同步更新本文件。**

所有模型调用都经过 provider 层，按“模型任务”路由（ADR 0002、0004）；每次调用记录在 `llm_usage`（不含 prompt 和输出内容）。

## 活动记录（学习者看到的“私教做了什么”）

下面每个步骤跑完都在 `agent_activities` 记一行（`app/activity/service.py` 的 `STEPS` 登记了步骤名、类型和可公示的摘要字段），在每条私教回复下显示：默认收起成一行，点开看明细；设置 →“显示”可以在本浏览器隐藏（只影响显示）。

- **一轮**以学习者那条消息的 id 为键；练习会话的开场没有学习者消息，固定用 `opening`。对话中的步骤通过 SSE `activity` 事件实时推送；回复后的后台步骤由前端在 60 秒内轮询 `GET /conversations/{id}/activity?turn=…`。
- **摘要只含白名单字段**：数量、记忆 id、语法点 id、错误类型和严重度、学习者自己的原话和改正。不含 prompt、模型原始输出、错误原文；失败只记 `failed`，没配模型记 `skipped`。
- **记忆只存引用**：展示时取记忆的当前内容，学习者删掉的显示“已删除”，活动里不留副本。删除会话时它的活动一起删除。

| 步骤名 | 类型 | 摘要字段 |
|---|---|---|
| `load_context` | step | `facts`、`episodes`（真正放进 prompt 的记忆 id）、`profile_items`（画像项数）、`practice_kc`（练习会话的语法点 id，普通对话为空） |
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
| 读取练习指引（只在练习会话） | `chat/practice.py` `DatabasePractice`，在 `load_context` 里 | 会话的 `focus_kc_id`；该语法点的目录信息、掌握度档位（不给模型数字）、最近 2 条对话错误原句 → 改正 | 无（只放进本次 prompt，不进 checkpoint）；活动 `load_context` 的 `practice_kc` | 无 | 对话顶部“语法练习：…”和“查看依据”；`/learner` 删除证据后下一轮就不再使用 |
| 私教回复 | `agents/chat_graph.py` `tutor` | 对话历史、学习者上下文、练习指引、本轮附件 | checkpoint（对话历史） | `llm/chat`；带图片时 `llm/vision` | 对话页；删除会话即删除 |

### 练习会话的开场（学习者打开练习会话时执行一次）

`POST /conversations/{id}/opening`：只对还没有任何消息的练习会话生效，由前端在打开这样的会话时自动调用（P1 计划 §7.5.3，Q19a）。

| 步骤 | 代码 | 读 | 写 | 模型任务 | 学习者在哪里能看到 / 撤销 |
|---|---|---|---|---|---|
| 私教开场 | `api/chat.py` `open_practice` → 同一张图；`tutor` 在本次调用末尾加一条开场提示（`prompts/practice_opening.md`，不进 checkpoint，也不以学习者名义保存） | 同上两行（学习者上下文、练习指引） | checkpoint（只有私教的开场白）；活动 `load_context`（turn `opening`）；不安排反思 | `llm/chat`，`llm_usage` 记为 `practice_opening`（不计入看板的对话轮数和打卡） | 对话页第一条消息；删除会话即删除 |

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

## 入学测（独立页面，不经过模型）

入学测是学习者主动做的测试，不调用任何模型：选题、判分、定级都是纯函数（`adaptive/placement/`），LangGraph 子图只负责编排和断点续做。不写 `agent_activities`（活动挂在对话的某一轮上，入学测不属于任何对话），结果页本身就是公示。

| 步骤 | 代码 | 读 | 写 | 学习者在哪里能看到 / 撤销 |
|---|---|---|---|---|
| 出题与作答 | `agents/placement_graph.py`（`pick → ask(interrupt)`）、`placement/service.py` | 词库 `words`（词频前 2 万的可考词）、假词清单、语法题库、`placement_item_stats`（作答够 30 次的题用校准难度） | checkpoint（种子和作答；做完即删）；`placement_sessions` | `/placement` 页面；`restart` 放弃当前测试 |
| 结果写回 | `adaptive/placement/writeback.py`（子图 `finish` 调用，一个事务，重复调用不重复写） | 本次作答 | `placement_sessions.result`；`user_profiles.cefr_level`（总体等级 = 语法等级）；`skill_estimates`（grammar、vocab）；`kc_evidence`（`source=placement`，每道语法题一条识别证据，错题不存选项和答案）；重放 `kc_mastery`；`placement_item_stats`（测后用最终能力回算题目难度，全站共用，不含个人信息） | 结果页（总体等级、语法分项、估计词汇量和仅供参考的词汇等级；可重新测试）；`/memory` 改等级；`/learner` 技能估计显示等级和词汇量，每条证据标“来自入学测”，可查看、删除 |
| 按词汇量批量标熟 | `services/vocab/placement_known.py` → `GET/POST/DELETE /vocab/placement-known` | 最近一次入学测的词汇结果、当前词书 | `user_cards`（学习者确认后，为当前词书里词频排名在“认识概率 ≥ 90%”以内、还没有卡片的词建 `source=placement` 的 known 卡） | 结果页、筛选页的“跳过已经认识的常用词”卡片（点确认才执行，显示已标熟多少个）；“撤销”即 `DELETE` 整批撤销（只删仍是 known 的这类卡片） |

## 看板学习建议（打开看板时按需在后台执行）

算法出候选、模型只挑选和写理由（P1 计划 §7.5.2）。打开看板只读缓存，不等模型；缓存过期时在后台重新生成。

| 步骤 | 代码 | 读 | 写 | 模型任务 | 学习者在哪里能看到 / 撤销 |
|---|---|---|---|---|---|
| 生成候选（不调模型） | `advice/candidates.py` | 今日待复习 / 剩余新词、当前词书与筛选进度、最近一次完成的入学测、最近 14 天对话里计入的语法错误（KC、掌握度、最多 2 条原句 → 改正） | 无 | 无 | 看板“今天的建议”：每条旁边的实时数字 |
| 挑选并写理由 | `advice/writer.py`、`advice/service.py` `AdviceRefresher`（进程内，每个学习者同时只一个任务；没有缓存、超过 12 小时、候选或界面语言变了且距上次满 10 分钟时触发；也可手动刷新，一小时一次） | 候选及证据（含上面的错误原句）、画像（等级、目标、考试、每日时长、兴趣） | `learning_advice`（每人一行，只存模型写的条目；不在候选里的 id、重复、空文本丢弃；没配模型或失败时记下状态、不存条目） | `llm/advice`（走默认路由） | 看板“今天的建议”：模型写的条目标“AI”，其余是模板；说明生成时间或“没配置模型 / 生成失败”。建议只是链接，没有副作用；删除账号时随之删除 |
