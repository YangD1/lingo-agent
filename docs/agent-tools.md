# Agent 工具与后台步骤清单

私教 agent 用到的每个工具、MCP 服务和后台步骤都登记在这里（ADR 0013）。**新增或修改时必须同步更新本文件。**

所有模型调用都经过 provider 层，按“模型任务”路由（ADR 0002、0004）；每次调用记录在 `llm_usage`（不含 prompt 和输出内容）。

## AI 用量标记（学习者点之前看到的）

事后看“私教做了什么”（下一节），事前看 AI 标记（ADR 0014）：每个会调用模型的入口旁都有一个小“AI”标，悬停、聚焦或点按显示这个入口触发哪些调用、立即还是在后台、每次约多少 token（按本租户最近 20 次的平均，没有记录时用默认估计）、当前会用的模型。清单在 `backend/app/usage/features.yaml`，接口是 `GET /usage/estimates`。**新增会调用模型的功能时，同步登记到那份清单并挂上标记。**

| 功能（清单里的 key） | 入口 | 触发的调用（task） |
|---|---|---|
| `chat_message` | 聊天输入框“发送”；看板和入学测结果页对话框的输入框、看板的快捷回复（ADR 0016） | `chat`（立即）；私教调用了工具时再加 `chat_tools`（拿到工具结果后的回复，走 `chat` 路由）；`reflect`、`memory` 向量化（回复后在后台） |
| `chat_image` | 聊天输入框“附件” | `vision`（每张图；带图的那一轮回复也走 `vision`） |
| `chat_pdf` | 同上 | `vision`（只有扫描页，每页一次） |
| `chat_audio` | 聊天输入框“录音” | `asr`（按音频秒数） |
| `practice_start` | 看板常错语法点的“对话练”、`/learner` 语法点详情和私教练习卡片的“对话练习” | `practice_opening`（走 `chat` 路由） |
| `plan_start` | 入学测结果页对话框里的“和私教聊聊这次结果” | `plan_opening`（走 `chat` 路由）；之后每轮同 `chat_message` |
| `memory_edit` | `/memory` 记忆列表（添加、修改） | `memory` 向量化 |
| `word_examples` | 私教气泡里单词气泡的“AI 例句”（ADR 0017）；复习卡片背面的“AI 例句”（ADR 0020） | `word_examples`（立即；同租户同词同等级只调一次，之后读缓存） |
| `message_translate` | 私教气泡下的“看中文 / 看英文”（ADR 0017） | `translate`（立即；每条消息每种语言只调一次，之后读缓存） |
| `practice_set` | `/practice` 落地页“开始一组 / 继续上次的练习”、总结页“再来一组”；学习者模型每个语法点、私教练习卡片、看板建议里的“做一组题” | `exercise_generate` + `exercise_critic`（立即；被拒的题最多再重写审两轮）；做完一组后在后台为下一组再各调一次 |
| `practice_grade` | `/practice` 开放题的提交按钮旁（也和 `practice_set` 一起挂在开组入口）；find_fix 的改法不在答案列表里时同样调用 | `exercise_grade`（立即；每题只批第一次作答；选择题、填空、和参考答案一致的答案由代码判，不调模型） |

设置页的“测试连接”不挂标记：只给管理员用，每次几个 token，且不走路由（ADR 0014 §4）。

### 对话之外的调用

`word_examples`、`translate` 由学习者在界面上点了才调用，不属于任何一轮对话，所以不写 `agent_activities`（和入学测一样）。缓存命中时不调模型，也不记 `llm_usage`。

| 调用 | 代码 | 读取 | 写入 | 学习者在哪看到 / 撤销 |
|---|---|---|---|---|
| AI 例句 | `services/vocab/examples.py` → `POST /vocab/words/{id}/examples` | 词条（单词、中文释义）、学习者等级（没有时按 A2） | `word_examples`（租户 + 词 + 等级；每句经代码校验含该词或其变形，都不合格时不写） | 单词气泡和复习卡片背面显示；不含个人信息，无需撤销 |
| 气泡翻译 | `chat/translate.py` → `POST /conversations/{id}/messages/{message_id}/translate` | 这条私教消息的文本 | `message_translations`（会话 + 消息 + 目标语言，删除会话时一起删） | 私教气泡原位切换显示；随会话删除 |

查词（`GET /vocab/lookup`）和朗读（浏览器 `speechSynthesis`）不调用模型。

## 活动记录（学习者看到的“私教做了什么”）

下面每个步骤跑完都在 `agent_activities` 记一行（`app/activity/service.py` 的 `STEPS` 登记了步骤名、类型和可公示的摘要字段），在每条私教回复下显示：默认收起成一行，点开看明细；设置 →“显示”可以在本浏览器隐藏（只影响显示）。

- **一轮**以学习者那条消息的 id 为键；练习会话的开场没有学习者消息，固定用 `opening`。对话中的步骤通过 SSE `activity` 事件实时推送；回复后的后台步骤由前端在 60 秒内轮询 `GET /conversations/{id}/activity?turn=…`。
- **摘要只含白名单字段**：数量、记忆 id、语法点 id、错误类型和严重度、学习者自己的原话和改正。不含 prompt、模型原始输出、错误原文；失败只记 `failed`，没配模型记 `skipped`。
- **记忆只存引用**：展示时取记忆的当前内容，学习者删掉的显示“已删除”，活动里不留副本。删除会话时它的活动一起删除。

| 步骤名 | 类型 | 摘要字段 |
|---|---|---|
| `load_context` | step | `facts`、`episodes`（真正放进 prompt 的记忆 id）、`profile_items`（画像项数）、`practice_kc`（练习会话的语法点 id，普通对话为空）、`planning`（规划对话：读了入学测结果和建议候选） |
| `reflect_memory` | background | `added`、`updated`（记忆 id）、`deleted`（只计数）、`profile_fields`；挂在一批反思的最后一条学习者消息上 |
| `grammar_tagging` | background | `mistakes`（`kc_id`、`error_type`、`severity`、`original`、`correction`）、`used_correctly`（KC id）；每条学习者消息一行。摘要里有错误原句的副本，所以学习者在 `/learner` 删掉一条证据时，这里对应的一项也去掉；“删除所有学习记录”时这些行全部删除 |
| `vocab_collect` | background | `added`、`existing`（`word_id` + 拼写：新收进生词本的词、已有卡片没有改动的词）；挂在提问的那条学习者消息上，没有收到词的消息不记。接口另返回 `words_on_list`（仍在生词本里的收词），明细据此显示“已移出” |
| `summarize` | background | `episode_id` |
| `propose_word_book`、`propose_learning_goal`、`suggest_practice`、`suggest_link` | tool | `card_id`、`card_kind`（出了卡片时；调用被拒记 `failed`、摘要为空）；`call_id` = 模型的 tool call id。卡片本身显示当前状态 |
| `tools` | step | 无；只在厂商拒绝工具调用、这一轮改为不带工具重答时记一行 `skipped` |

新增工具时在 `STEPS` 登记，类型用 `tool` 或 `mcp`，同一轮多次调用用 `call_id` 区分。

## 学习者在对话里的操作（不经过模型）

| 操作 | 代码 | 写 | 学习者在哪里能看到 / 撤销 |
|---|---|---|---|
| 在私教回复的单词气泡里加入生词本（ADR 0017） | 前端 `components/chat/word-popup.tsx` → `POST /vocab/mine`（加的是查到的词条，比如 went 加的是 go） | `user_cards`（`source=manual`，规则同生词本页：精确 → 忽略大小写 → 还原原形；已标“认识”的词变回待学） | 单词气泡里提示结果；`/vocab/mine` 可删除 |

## LLM 工具调用（模型决定是否调用）

私教的工具（ADR 0015）。**工具只出卡片，不直接改任何设置**：有副作用的提议要学习者在卡片上点确认才执行，执行后可撤销；没有副作用的卡片只是链接。

- **身份不进参数**：参数里只有词书 id、目标、语法点 id 这类内容；学习者、会话、这一轮由接口层绑定（`cards/runtime.py` `DatabaseTutorTools`），模型填了多余字段一律拒绝。
- **上限**：一轮最多 2 次工具往返，每次最多 3 个调用（多出的直接返回错误），每个调用 15 秒超时；到上限后最后一次调用不带工具，提示里说明不能再调用。
- **失败不中断**：参数不合法、超出范围、超时，都作为工具结果（`status=error`）返回给模型，由它向学习者解释；厂商拒绝工具调用（400 / 404 / 422）时这一轮不带工具重答，只能给站内链接（`prompts/tutor_no_tools.md`），活动记 `tools: skipped`。
- **不带工具的情况**：练习会话（有 `focus_kc_id`）、带图片的一轮、上限已到。
- **规划对话和看板“今天”对话里的范围**（ADR 0015 §6、0016）：`suggest_practice` 的语法点只能是最近一次入学测答错且还没掌握的（最多 5 个）或建议候选里的，`suggest_link` 只能是建议候选对应的页面或 `/learner`；超出的调用作为错误返回。读不到候选时范围为空（只能出提议卡片）。
- **幂等**：同一个 tool call id 只写一张卡片；同一轮里同样的提议（类型和参数都相同）复用第一张卡片。
- **下一轮可见**：本会话最近 10 张卡片及其状态（待确认 / 已确认 / 已拒绝 / 已撤销）放进 system prompt，模型据此不重复提议。

| 工具 | 参数 | 卡片 | 确认后写 | 撤销 |
|---|---|---|---|---|
| `propose_word_book` | `book_id`（词书清单里的 id）、`daily_new`（可选，0–200） | 提议，`proposed` | `user_word_book`：换书时筛选进度归零，只在给了 `daily_new` 时改每日新词数；卡片记下原来的设置 | 恢复原来的词书、每日新词数和筛选进度（原来没有词书则删掉计划）；之后又改过设置则拒绝（409 `setting_changed`） |
| `propose_learning_goal` | `goal`（≤200 字）、`target_exam`（考试标签）、`daily_minutes`（1–600），至少一项 | 提议，`proposed` | `user_profiles` 对应字段，并记为学习者手动设置（`manual_fields`，反思不会覆盖）；卡片记下原值 | 恢复原值和原来的 `manual_fields`；之后又改过则 409 `setting_changed` |
| `suggest_practice` | `kc_id`（语法点清单里的 id） | 链接，`info` | 无（点开即建练习会话，同“开始练习”） | 不需要 |
| `suggest_link` | `kind`：`word_books`、`vocab_review`、`vocab_screen`、`placement`、`learner` 之一 | 链接，`info`；列表接口附实时数字（待复习数、筛选进度、距上次入学测天数等） | 无 | 不需要 |

卡片存在 `tutor_cards`（`cards/service.py`；状态 `proposed → applied | declined`、`applied → undone`，链接卡片是 `info`；提议不过期），删除会话时一起删除。接口：`GET /conversations/{id}/cards`、`POST /cards/{id}/apply|decline|undo`（只能操作自己的卡片）。回复中的卡片通过 SSE `card` 事件实时推送。

**学习者在哪里看到**：卡片显示在那一轮私教回复的下方（`frontend/src/components/chat/tutor-cards.tsx`），和回复一起属于对话，不受“显示私教做了什么”开关影响。提议卡片上有“确认 / 不用了”，确认后可“撤销”；撤销被拒绝（之后又改过设置）时卡片上说明原因。每次调用在“私教做了什么”里记一行（展示了什么卡片，或没能展示）；厂商不支持工具时也有一行说明。

## MCP 服务

目前没有。

## 对话流程中的步骤（每轮都执行）

| 步骤 | 代码 | 读 | 写 | 模型任务 | 学习者在哪里能看到 / 撤销 |
|---|---|---|---|---|---|
| 读取学习者上下文 | `agents/chat_graph.py` `load_context` | 画像、事实记忆、相关的会话摘要 | 无（只放进本次 prompt，不进 checkpoint）；活动 `load_context` | `embedding/memory`（有配置时用于检索摘要） | 回复下“私教做了什么”；`/memory` 页面查看、修改、删除 |
| 读取练习指引（只在练习会话） | `chat/practice.py` `DatabasePractice`，在 `load_context` 里 | 会话的 `focus_kc_id`；该语法点的目录信息、掌握度档位（不给模型数字）、最近 2 条对话错误原句 → 改正 | 无（只放进本次 prompt，不进 checkpoint）；活动 `load_context` 的 `practice_kc` | 无 | 对话顶部“语法练习：…”和“查看依据”；`/learner` 删除证据后下一轮就不再使用 |
| 选择由谁回复（supervisor） | `agents/chat_graph.py` `supervisor`；路由在开跑前由 `agents/routing.py` `route_for` 定 | 会话有没有练习语法点（`focus_kc_id`） | 无 | 无（不调模型，ADR 0023 §3） | 不单独显示：练习会话由 grammar_coach 回复，其余（含规划、今天的学习）由 tutor 回复，会话本身已经说明了这一点（Q37b）；自由对话的分类转交在任务 38 加入后才会记一步 |
| 私教回复（tutor） | `agents/chat_graph.py` tutor 子图：`tutor`（⇄ `tools`，见上一节） | 对话历史、学习者上下文、规划简报、本轮附件、本会话最近的卡片 | checkpoint（对话历史，含工具调用和结果，由主图保存；子图自己不存 checkpoint）；`tutor_cards` | `llm/chat`；带图片时 `llm/vision`；工具之后的回复记为 `chat_tools` | 对话页；删除会话即删除 |
| 练习会话回复（grammar_coach） | `agents/chat_graph.py` grammar_coach 子图：`grammar_coach`，不带工具 | 对话历史、学习者上下文、练习指引、本轮附件 | checkpoint（对话历史，由主图保存） | `llm/chat`；带图片时 `llm/vision` | 对话页；删除会话即删除 |

### 规划对话（嵌在入学测结果页，ADR 0015 §6、0016 §4）

`POST /conversations` 带 `purpose: "planning"` 创建（还没有任何消息的规划对话直接复用），`POST /conversations/{id}/opening` 让私教先开口，之后和普通对话一样每轮带工具。

| 步骤 | 代码 | 读 | 写 | 模型任务 | 学习者在哪里能看到 / 撤销 |
|---|---|---|---|---|---|
| 读取规划依据（每轮） | `chat/planning.py` `DatabasePlanning`，在 `load_context` 里 | 最近一次完成的入学测结果（等级、语法、词汇量）；该次答错且还没掌握的语法点（最多 5 个，含掌握度）；看板建议的候选（同“看板学习建议”，含最近对话里的错误原句） | 无（只放进本次 prompt，不进 checkpoint）；活动 `load_context` 的 `planning`；同时决定本轮卡片范围 | 无 | 回复下“私教做了什么”；入学测结果页；`/learner` 删除证据后下一轮就不再使用 |
| 私教开场 | `api/chat.py` `open_practice`（同一接口）；tutor 在本次调用末尾加开场提示（`prompts/plan_opening.md`，不进 checkpoint） | 同上 + 学习者上下文 | checkpoint（只有私教的开场白）；活动 `load_context`（turn `opening`）；不安排反思 | `llm/chat`，`llm_usage` 记为 `plan_opening` | 对话页第一条消息；删除会话即删除 |

### 练习会话的开场（学习者打开练习会话时执行一次）

`POST /conversations/{id}/opening`：只对还没有任何消息的练习会话生效，由前端在打开这样的会话时自动调用（P1 计划 §7.5.3，Q19a）。

| 步骤 | 代码 | 读 | 写 | 模型任务 | 学习者在哪里能看到 / 撤销 |
|---|---|---|---|---|---|
| 私教开场 | `api/chat.py` `open_practice` → 同一张图；grammar_coach 在本次调用末尾加一条开场提示（`prompts/practice_opening.md`，不进 checkpoint，也不以学习者名义保存） | 同上两行（学习者上下文、练习指引） | checkpoint（只有私教的开场白）；活动 `load_context`（turn `opening`）；不安排反思 | `llm/chat`，`llm_usage` 记为 `practice_opening`（不计入看板的对话轮数和打卡） | 对话页第一条消息；删除会话即删除 |

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

## 练习组的出题与批改（ADR 0021 §3–§4、§6，任务 33–35）

练习组不属于任何对话，不写 `agent_activities`；每组题怎么来的记在 `exercise_sets` / `exercises` 里，练习页（`/practice`）用 `service.how_made()` 公示（模型出了几题、题库补了几题、审题拒掉几题、出题和审题的模型名；不显示被拒的题和审题理由），组做完后的总结页同样显示。入口挂 `practice_set` 的 AI 标记，开放题提交处挂 `practice_grade`。开组时（第一次作答或举报）记下本组语法点的掌握度快照（`exercise_sets.mastery_before`），总结页据此显示掌握度前后和新学会的语法点。

| 步骤 | 代码 | 读 | 写 | 模型任务 | 学习者在哪里能看到 / 撤销 |
|---|---|---|---|---|---|
| 开始一组 / 预生成下一组 | `api/practice.py` `POST /practice/sets` → `adaptive/exercise/worker.py` `PracticeWorker.start` / `prefetch`（先继续最近一组没做完的；指定语法点时该语法点最多占 `max_items_per_kc` 题，不用预生成组；组做完或最后一题被举报时预生成下一组） | 学习者现有的练习组；指定的语法点 | `exercise_sets`（`generating`；预生成组 `origin=prefetch`，没人开始过的超过 24 小时或规则变了标 `failed/expired`） | 无 | 练习页；预生成的开关在任务 40 接入设置页 |
| 选题 | `adaptive/exercise/inputs.py`、`planner.py`（纯算法） | `kc_mastery`、近 30 天计入错误、`skill_estimates`（grammar）、画像等级；`rewrite_own` 取近 30 天对话里自己的错句（优先没出过题的） | `exercise_sets.kc_plan`、`rules_version` | 无 | 练习页显示每题的语法点；`/learner` 删除证据后下一组就不再使用那句话 |
| 出题 | `agents/exercise_graph.py` `generate`，提示词 `prompts/exercise_generate.md` | 计划里的语法点（说明、常见错误）、目标难度、学习者等级、讲解语言、画像的职业 / 目标 / 考试 / 兴趣、最近 8 条事实记忆、`rewrite_own` 的原句和改正；重写时附被拒草稿和理由 | 无（草稿先给审题） | `llm/exercise_generate`（走默认路由） | — |
| 审题 | 同上 `critic`，提示词 `prompts/exercise_critic.md`，判定 `adaptive/exercise/drafts.py` `judge` | 学习者能看到的题面；开放题的参考答案；语法点说明；不含个人信息和答案 | `exercises`：通过的 `status=ok`，被拒的 `status=rejected`（只用于评估审题，不给学习者），`critic` 存判定、理由、独立作答、两方评级和模型名 | `llm/exercise_critic`（默认先用另一家模型，温度 0） | 练习页的“这组题怎么来的” |
| 题库补位 | `adaptive/exercise/bank.py` | 入学测题库、学习者做过的题库题（入学测和练习） | `exercises`（`bank_item_id`，`critic` 为空） | 无 | 练习页标“题库题” |
| 作答与批改 | `adaptive/exercise/answer.py` `answer`；代码判 `grading.py`；模型判 `grader.py`，提示词 `prompts/exercise_grade.md` | 题目（含答案）、学习者答案；模型只收到题面、参考答案、目标语法点和语法点清单，讲解语言取画像，不含其他个人信息 | `attempts`（每题只记第一次，`feedback` 存讲解、改正、其他错误、批改模型名）；`kc_evidence`（`source=exercise`，目标语法点按题型记识别 / 产出，其他错误各记一条，KC 必须在清单里且不是目标语法点）；重放 `kc_mastery`；`skill_estimates` grammar 走一步 Elo；`exercise_sets` 状态 ready → in_progress → done。批改模型失败时什么都不写，学习者重交 | `llm/exercise_grade`（默认路由） | 练习页每题的批改结果；`/learner` 页面的证据（可删除） |
| 举报有问题的题 | `adaptive/exercise/answer.py` `report` | 这题的作答 | `exercises.status=reported`；删掉这题作答产生的全部证据并重放掌握度（作答本身保留；语法能力那一步 Elo 不回退） | 无 | 练习页“这题有问题”；重复举报不变 |

## 入学测（独立页面，不经过模型）

入学测是学习者主动做的测试，不调用任何模型：选题、判分、定级都是纯函数（`adaptive/placement/`），LangGraph 子图只负责编排和断点续做。不写 `agent_activities`（活动挂在对话的某一轮上，入学测不属于任何对话），结果页本身就是公示。

| 步骤 | 代码 | 读 | 写 | 学习者在哪里能看到 / 撤销 |
|---|---|---|---|---|
| 出题与作答 | `agents/placement_graph.py`（`pick → ask(interrupt)`）、`placement/service.py` | 词库 `words`（词频前 2 万的可考词）、假词清单、语法题库、`placement_item_stats`（作答够 30 次的题用校准难度） | checkpoint（种子和作答；做完即删）；`placement_sessions` | `/placement` 页面；`restart` 放弃当前测试 |
| 结果写回 | `adaptive/placement/writeback.py`（子图 `finish` 调用，一个事务，重复调用不重复写） | 本次作答 | `placement_sessions.result`；`user_profiles.cefr_level`（总体等级 = 语法等级）；`skill_estimates`（grammar、vocab）；`kc_evidence`（`source=placement`，每道语法题一条识别证据，错题不存选项和答案）；重放 `kc_mastery`；`placement_item_stats`（测后用最终能力回算题目难度，全站共用，不含个人信息） | 结果页（总体等级、语法分项、估计词汇量和仅供参考的词汇等级；可重新测试）；`/memory` 改等级；`/learner` 技能估计显示等级和词汇量，每条证据标“来自入学测”，可查看、删除 |
| 按词汇量批量标熟 | `services/vocab/placement_known.py` → `GET/POST/DELETE /vocab/placement-known` | 最近一次入学测的词汇结果、当前词书 | `user_cards`（学习者确认后，为当前词书里词频排名在“认识概率 ≥ 90%”以内、还没有卡片的词建 `source=placement` 的 known 卡） | 结果页、筛选页的“跳过已经认识的常用词”卡片（点确认才执行，显示已标熟多少个）；“撤销”即 `DELETE` 整批撤销（只删仍是 known 的这类卡片） |

## 看板的“今天”对话（ADR 0016）

看板上嵌着一个私教对话框，每天一段（按学习者时区）。**打开看板不调模型**：先显示一句规则问候和几条快捷回复，学习者点快捷回复或自己发消息，才开始这一天的对话（懒创建，`POST /conversations` 带 `purpose: "daily"`，当天已有就返回那一段）。之后和普通对话一样：带工具、有后台反思、进对话列表。没有开场白。

| 步骤 | 代码 | 读 | 写 | 模型任务 | 学习者在哪里能看到 / 撤销 |
|---|---|---|---|---|---|
| 生成候选（不调模型） | `advice/candidates.py` → `GET /advice` | 今日待复习 / 剩余新词、当前词书与筛选进度、入学测提醒（`advice/reminder.py`：原因、上次测试的等级和该级语法点学会几个、学习者是否点过“以后再说”）、最近 14 天对话里计入的语法错误（KC、掌握度、最多 2 条原句 → 改正）；chat 路由能否解析出模型（`model_ready`） | 无 | 无 | 看板对话框的问候和快捷回复（带实时数字）；没配模型时显示为直达链接 |
| 快捷回复 | 前端按候选和界面语言用模板生成；点了就作为学习者的消息发送 | 候选 | 同普通对话的一轮（学习者消息、回复、活动、卡片、反思） | 同 `chat_message` | 对话框和对话页的历史里；删除会话即删除 |
| 读取今天的依据（每轮） | `chat/planning.py` `DatabasePlanning`（`purpose="daily"`，提示词 `prompts/daily.md`），在 `load_context` 里 | 同规划对话：最近一次入学测结果、该次答错且还没掌握的语法点、候选（入学测提醒带原因；没被搁置时私教第一条回复提一次，点过“以后再说”的只在被问到时给卡片，页面上不显示） | 无（只放进本次 prompt，不进 checkpoint）；活动 `load_context` 的 `planning`；同时决定本轮卡片范围（与规划对话相同） | 无 | 回复下“私教做了什么”；`/learner` 删除证据后下一轮就不再使用 |
