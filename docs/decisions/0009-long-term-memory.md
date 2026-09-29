# 0009 · 长期记忆：存储、抽取与读取

- **状态**：已采纳（2026-09-29，`docs/plans/P1-mvp.md` Q2–Q4 按推荐确认）
- **日期**：2026-09-29
- **影响**：新增 `user_profile`、`memories` 表，`conversations` 加 `reflected_message_id`；主图加 `load_context` 节点；新增 LLM 路由任务 `reflect`（记忆抽取和会话摘要共用）。PLAN 第二节“长期记忆”一行（LangGraph Store + LangMem）以本 ADR 为准。

## 背景
PLAN 把记忆分成三类：画像、情景记忆、结构化学习者模型（后者见 ADR 0010）。原计划用 LangGraph `PostgresStore` 存记忆，LangMem 做抽取。落地前核实了两者的现状：

1. **Store 的语义索引和多租户 embedding 冲突**。`AsyncPostgresStore(conn, index={"dims": N, "embed": ...})` 在创建时固定一个 embedding 函数和维度，`store_vectors` 表的向量列也按这个维度建。而本项目的 embedding 模型由租户各自配置（ADR 0004），不同租户可能用不同模型、不同维度，一个进程里的一个 Store 装不下。
2. **LangMem 基本停止发布**：最新版本 0.0.30 发布于 2025-10，之后没有新版本；依赖 trustcall、langsmith、langchain-openai、langchain-anthropic，偏重。
3. 用户必须能查看、编辑、删除自己的记忆（项目约束）。用业务表存储，删除、级联、迁移、权限都和其他表一致。

## 决定

### 1. 存储：自建表
- `user_profile`：结构化画像（母语、目标、目标考试、兴趣、职业、每日时长、讲解语言、CEFR 等级、时区），一人一行。`manual_fields` 记录用户手动改过的字段，反思不覆盖这些字段。
- `memories`：id、user_id（FK 级联删除）、kind[`fact` | `episode`]、content、source_conversation_id（可空，会话删除时置空）、embedding（`vector`，不带维度，可空）、embedding_model、created_at、updated_at。
  - `fact`：关于学习者的事实（“做后端开发”“下个月面试”“喜欢用中文讲语法”），条数少，**每次全部注入**（上限 40 条，超出按更新时间取最新）。
  - `episode`：每个会话一条摘要，随会话进展覆盖更新；**按相关性检索**若干条注入。
- 删除是真删除。

### 2. 检索：embedding 可选
- 租户配了 `embedding` 路由：写入记忆时顺带算向量；检索时按用户过滤，再用余弦距离精确排序（每个用户的记忆只有几十到几百条，不需要 ANN 索引，也就不需要固定维度）。只比较 `embedding_model` 和当前模型一致的行；租户换了模型后，旧向量在下次写入或后台补算时更新。
- 没配 embedding：情景记忆按更新时间取最近几条。对话不因为没配 embedding 而失败。

### 3. 抽取：回复之后的后台反思
- SSE 发出 `done` 之后，把这一轮交给进程内的 `ReflectionWorker`（与 `AttachmentProcessor` 同一模式：单 worker、不引入任务队列）。同一会话串行，全局并发默认 2。
- 一次结构化调用（task `reflect`）同时输出记忆操作、画像更新、错误打标、用对的 KC、生词候选（后三项见 ADR 0010、0011）。记忆操作仿照 LangMem：把现有事实（带 id）给模型，模型输出 `add` / `update(id)` / `delete(id)`，由代码执行并校验 id 属于该用户。
- 会话摘要每 6 轮重写一次，学习者新建会话时把上一个会话剩下的部分也总结进去；和记忆抽取共用 `reflect` 路由。
- `conversations.reflected_message_id` 记录已处理的位置。进程重启后丢掉的反思在 worker 启动时和该会话下一条消息到来时补做。
- 反思失败只记日志，不影响对话。

### 4. 读取：只进 prompt，不进 checkpoint
`load_context` 节点把画像、事实、相关摘要、学习者模型摘要拼成 system prompt 的一部分，只用于本次调用。用户删掉一条记忆后，下一轮立刻不再使用。

## 取舍
- 不用 Store 就少了 LangGraph 生态里现成的 `search_memory` 工具等集成；P1 的记忆由图节点主动注入，不需要这些工具。以后要做“Agent 主动查记忆”的工具，基于自建表写一个也很简单。
- 每轮多一次 LLM 调用。反思用单独的路由 task，租户可以给它配便宜模型。
- 事实记忆全部注入会占 prompt 长度。设了条数上限；以后记忆多了，再改为“画像全部注入 + 事实按相关性检索”。
- 反思在进程内执行，多 worker 部署时需要换成外部队列或数据库锁，和 P0 的会话锁一起放到 P4。

## 落地记录（2026-09-29，任务 2、3）
- 表名用 `user_profiles`（和其他表一样用复数）。`explanation_language` 可为空、没有默认值：只有学习者或反思明确设置过才写进 prompt，否则分不清“选了中文”和“没设置”。
- embedding 路由的 task 名是 `memory`（没配时按 embedding 默认路由）。检索时情景记忆不超过需要的条数就直接返回，不调 embedding，避免每轮首字前多一次网络请求。
- 学习者上下文放在图状态的 `learner_context` 字段里，通道类型是 LangGraph 的 `UntrackedValue`：写入不进 checkpoint，也不进 pending writes（`langgraph/pregel/_loop.py` 里按通道类型过滤），测试直接扫描 checkpoint 三张表确认没有残留。图的输入/输出 schema 仍是 `MessagesState`，调用方看不到这个字段。
- 读取记忆失败只记日志，本轮照常回复（不带学习者上下文）。

## 落地记录（2026-09-29，任务 4）
- 只用一个路由任务 `reflect`（记忆抽取和会话摘要共用），租户只需为“后台整理”配一次便宜模型。设置页的路由编辑器目前写死了 chat / vision / asr 三项，`reflect` 的入口在任务 5 加；没配时按默认路由兜底。
- 记忆用什么语言写：取前端的语言 cookie（`NEXT_LOCALE`，ADR 0006），简体中文界面写中文，其他写英文，这样学习者能在记忆页里看懂、修改。
- 游标 `reflected_message_id` / `summarized_message_id` 存在会话行里；更新时显式保留 `updated_at`，否则后台整理会把会话顶到列表最前。没有游标时（P1 之前的旧会话）只看最近 6 条消息。
- 每个调用最多重试 1 次，仍失败就跳过这一轮（游标照样前移），不会无限重试；没配模型时直接跳过。
- 模型只看到短 id（`m1`、`m2`……），由代码映射回该学习者的记忆；每轮最多新增 5 条、总数上限 100 条，重复的不再添加。画像更新逐字段清洗，`target_exam` 只接受词书标签，CEFR 等级不能由反思修改。
- 部署方可以用 `MEMORY_REFLECTION_ENABLED=false` 关闭（省调用；已有记忆照常使用）。启动时对最近一天活跃的会话补做。
- E2E 的设置页用例里，用量从 2 次调用变为 3 次：多出的是回复后的反思调用，这是开启记忆后真实的成本。
