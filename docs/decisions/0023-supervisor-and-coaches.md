# 0023 · Supervisor 主图与各 coach 子图

- **状态**：已采纳（2026-10-02，任务 30；D4、Q9、Q10 按推荐确认）
- **日期**：2026-10-02
- **影响**：`agents/chat_graph.py` 的主图改为 `load_context → supervisor → {tutor, grammar_coach, writing_coach, reading_coach}`；`api/chat.py::_reply` 里按会话类型分支的逻辑挪进路由；新增模型任务 `route`（只有自由对话才调）；新增 `writing_submissions` 表、`/writing` 页；`conversations.purpose` 加 `writing` / `reading`；活动公示多一个“路由”步骤。

## 背景
P1 的对话图是 `START → load_context → tutor ⇄ tools → END`（ADR 0015 §1）。不同会话的行为差异写在 `api/chat.py::_reply` 里：有 `focus_kc_id` 的语法练习会话不给工具；`purpose` 为 planning / daily 的会话给有限的工具；自由对话给全部工具。P2 要加写作和阅读，各自需要不同的提示词、工具和上下文（作文、文章），继续在 `_reply` 里堆 if 会越来越难维护，也不符合 PLAN 的 Supervisor 设计（ADR 0009 把它从 P1 移到了 P2）。

## 决定
1. **时机（Q9）**：P2b 有了第二个 coach（写作）时再加 Supervisor，P2a 不动对话图。
2. **主图**：`START → load_context → supervisor → 某个 coach → END`。每个 coach 是子图，有自己的提示词和工具集，内部仍是 `coach ⇄ tools` 的循环（工具轮数上限、并行、失败作为结果返回等规则不变，ADR 0013）；所有 coach 共享 `ChatContext` 和同一个 checkpoint 线程，切换 coach 不丢历史。
3. **路由先看确定的信号，不调模型**：
   - 会话有 `focus_kc_id` → grammar_coach（不给工具，同现在）；
   - `purpose` 为 planning / daily → tutor（有限工具，同现在）；
   - 从 `/writing`、`/reading` 发起的会话（`purpose` 为 writing / reading）→ 对应 coach。
   只有自由对话才调用一次轻量结构化分类（task `route`，可以配便宜模型）：判断这一轮要不要转给写作 / 阅读 / 语法 coach。分类失败、超时或置信度低，都留在 tutor。路由结果是一个 Pydantic 枚举，不解析自由文本。
4. **`_reply` 只负责组装 context**：各会话类型的提示词和工具范围由路由决定，`_reply` 不再按类型分支。
5. **写作入口（Q10）**：独立的 `/writing` 页（写作框、字数统计、逐句对照、历史）和对话内批改（学习者在对话里贴作文，路由给 writing_coach）共用同一个批改服务（task `writing_review`）和 `writing_submissions` 记录；对话里的回复带一张卡片，链到这条记录。写作批改的错误按 ADR 0012 记证据（`source=writing`，production）；四维评分只展示，不进掌握度。
6. **公示**：路由结果作为一个步骤（例如“交给了写作 coach”）出现在“私教做了什么”里（ADR 0013），同步 `docs/agent-tools.md`；`route` 调用登记到 `features.yaml`（ADR 0014）。

## 落地记录（任务 37，2026-10-02）
- Q37a–c 按推荐确认：自由对话的轻量分类（task `route`）和“转给了某个 coach”的活动步骤挪到任务 38，和 writing_coach 一起上——37 结束时自由对话除了 tutor 没有别的去处，提前分类只会每轮白花一次调用；按确定信号的路由不记活动步骤；coach 用子图。
- 代码：`agents/routing.py`（`Route`、`route_for(focus_kc_id)`：有语法点 → grammar_coach，其余 → tutor；`purpose` 只决定 tutor 拿到的简报和工具范围，不参与路由）；`api/chat.py::_reply` 按路由组装来源；`chat_graph.py` 主图 `load_context → supervisor → {tutor, grammar_coach}`，`supervisor` 返回 `Command(goto=route)`；开场提示按 coach 定（tutor `plan_opening`、grammar_coach `practice_opening`）；`chat/turn.py` 用 `subgraphs=True` 收子图的 token 和自定义事件。
- **coach 子图不单独存 checkpoint**（`compile(checkpointer=False)`）：默认情况下子图会把自己的输入写进 `checkpoint_writes`，其中包括不该持久化的学习者记忆和练习指引（ADR 0009 §4），原有的隐私测试抓到了这一点。消息仍由主图保存，历史连续；代价是 coach 内部不能单独中断恢复，目前也用不到。
- 切换 coach 时别的 coach 留下的工具消息：37 里同一会话的路由固定不变，不会发生；任务 38 加入自由对话分类后，要测 tutor 留下工具调用、下一轮转给不带工具的 coach 的情况（有的厂商要求带工具定义才接受历史里的工具消息）。

## 落地记录（任务 38，2026-10-02 – 10-03）
- Q38a–f 按推荐确认。**自由对话分类（38.4）**：`agents/routing.py` `worth_classifying`（学习者这条消息打字的部分 ≥ 60 个英文单词才分类，Q38a）→ `classify`（task `route`，`RouteDecision` 枚举 tutor / writing_coach，带私教上一条回复末尾 600 字符，8 秒超时；没配模型、出错、超时都留 tutor，不另记失败步骤）；只在 `ChatContext.classify` 为真时做（`api/chat.py` `Turn.free_chat`：自由对话里学习者的消息，规划 / 今天的学习 / 练习 / 开场都不分类）。`providers.*.yaml` 加 `route` 路由（便宜模型、温度 0）。转给非 tutor 时记活动 `handoff`（Q37b）。**和本 ADR §3 不同**：没有“置信度”字段——分类只有两个去处，“拿不准就答 tutor”写在提示词里；阅读、语法 coach 等任务 43 再加进枚举，语法 coach 仍只由会话的语法点决定。
- **writing_coach（38.5）**：转过来的这一轮固定批改学习者刚发的文字（Q38b，不由模型决定）：`chat/writing.py` `DatabaseWriting` 用 `/writing` 同一个服务建记录（带 `conversation_id`）、交给 `WritingWorker` 并最多等 90 秒（超时不取消，批改在后台做完，卡片照样链过去），然后放一张 `writing` 卡片（迁移 `5e1a7c3d9b20`），再把总评、四维评分和按严重度排的前 8 处修改交给 coach 简短点评；批改失败也照常回复。活动步骤 `writing_review`。
- **切换 coach 时的工具消息**：writing_coach 不带工具，发给模型的历史里去掉 tutor 以前的工具调用和工具结果，只留回复文字（`without_tool_calls`），集成测试覆盖“tutor 用过工具、下一轮转给 writing_coach”。checkpoint 里的历史不变。
- `features.yaml` 的 `chat_message` 下登记了 `route` 和 `writing_review`（只在对应情况下发生，AiBadge 逐条列出）。`/writing` 页面和 E2E 在任务 39；在那之前卡片链接的 `/writing/{id}` 还没有页面。

## 取舍
- 只有自由对话才多一次分类调用，其他会话零额外延迟和 token；代价是自由对话里学习者突然要改作文时，要靠分类模型识别出来。分类出错的后果只是“由 tutor 回答”，tutor 本身也能讲语法和改句子，风险可控。
- 每轮都用模型路由更灵活，但只有一个 coach 时没有意义，而且每轮多一次调用。
- coach 共享一个 checkpoint 线程，历史连续；但各 coach 的提示词要注意不被别的 coach 留下的工具消息带偏，图测试里覆盖切换场景。
