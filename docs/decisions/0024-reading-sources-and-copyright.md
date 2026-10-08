# 0024 · 阅读来源与版权

- **状态**：已采纳（2026-10-02，任务 30；D3 修订）
- **日期**：2026-10-02
- **影响**：新增依赖 `feedparser`；新增 `feeds`、`feed_subscriptions`、`articles`、`article_versions`、`reading_sessions` 表；新增模型任务 `article_rewrite`；README 数据来源一节补充内置来源和许可。

## 背景
PLAN 原计划的阅读来源是 BBC / VOA Learning English / NPR / Guardian 等 RSS 加正文抽取；P2 计划（D3）定为内置 VOA Learning English（美国政府作品，公有领域）+ 学习者自加 RSS。

2026-10-02 开工前核实：

- **VOA Learning English**：`/rssfeeds` 列出的 40 多个 feed 全部停在 2025 年 3–4 月（最新一条 2025-04-29，多数在 3 月中），首页也没有新文章；而且这些 feed 只给 100–300 字的摘要，没有全文。VOA 在 2025 年 3 月被大规模停播，Learning English 没有恢复更新。
- **Wikinews**：英文 Wikinews 已被 Wikimedia 董事会批准关闭，现在只读。
- **The Conversation**：RSS 带全文，每天更新，但许可是 CC BY-ND（不允许演绎），分级改写就是演绎，不能用。
- **NASA 新闻稿**（`https://www.nasa.gov/news-release/feed/`）：美国政府作品，公有领域（NASA 的署名和标志不能用来暗示背书）；RSS 带全文（`content:encoded`），每天更新；内容偏科技和航天。
- **Global Voices**（`https://globalvoices.org/feed/`）：自己的文章是 CC BY 3.0（只要求署名，允许改写）；RSS 带全文，每天更新；内容是世界各地的社会与文化，单篇约 1,500–2,300 词，偏长。部分文章是从合作方转载的，正文里另标 CC BY-NC-ND。
- BBC、NPR、Guardian 的内容有版权；Guardian 开放平台要申请 key，条款限制较多。

## 决定
1. **内置来源**：NASA 新闻稿、Global Voices。两个都直接用 RSS 里的全文，不抓网页。~~Global Voices 正文里标了 NC-ND（或其他非 CC BY 许可）的文章跳过，不入库。~~ **2026-10-07 修订（任务 41，Q41a）**：实抓发现正文里的 CC BY-NC-ND / BY-NC / BY-SA 都是图片说明，不是文章的许可；合作方转载写成“This article / story was originally published by 〈机构〉… republished here with permission / under a partnership agreement”。改为：入库时去掉所有图片和图片说明，有这类转载声明的整篇跳过，其余标 `cc_by`。NASA 跳过 APOD（文字和图片作者不是 NASA）和不到 250 词的通知（Q41b）。
2. **学习者自加 RSS**：学习者可以加任意 RSS / Atom 地址（抓取复用 `providers/net_guard.py` 的 SSRF 防护，ADR 0004）。feed 带全文就用全文；只有摘要的条目在列表里标“只有摘要”，阅读页显示摘要并链到原文，不做分级改写。是否引入正文抽取（如 `trafilatura`，依赖 lxml）留到任务 41 实测内存后再定。
3. **出处与许可**：每篇文章存来源、原文链接、作者（有的话）和许可标记（`public_domain` / `cc_by` / `unknown`）。阅读页始终显示出处、原文链接和许可；改写过的文章写明“按你的等级改写”，CC BY 的写明许可和改动说明。`unknown`（学习者自加的源）只在这个学习者自己的阅读页显示。
4. **存储**：抓来的全文只存在部署方自己的数据库里，不进仓库（CLAUDE.md），不提供公开的分享或导出接口。内置来源的 `articles` 全局共用；学习者自加的源按租户隔离。
5. **改写缓存**：`article_rewrite` 的结果按（租户、文章、目标等级）缓存，同一租户里一篇文章同一等级只改写一次。不跨租户共享：改写花的是这个租户自己配置的模型和 token（ADR 0004）。
6. **抓取礼仪**：每个 feed 最多每 2 小时抓一次（ADR 0025 的定时任务），用 ETag / Last-Modified 条件请求，带可识别的 User-Agent；单个 feed 失败不影响其他 feed，连续失败的 feed 降低频率。

## 取舍
- 内置来源的话题偏窄（科技航天 + 世界社会文化），没有日常新闻；日常新闻靠学习者自加 RSS 补。比起抓正文、绕版权，这样的起点干净。
- Global Voices 原文偏长、偏难，改写时按等级截取或摘编；改写会损失细节，所以阅读页总是能切回原文链接。
- VOA Learning English 2015–2025 的存档（公有领域，本来就是给学习者写的）很合适做静态文库，但要逐篇抓网页、写解析器，P2 不做；以后要做时另开任务。
- 只有摘要的自加 feed 体验较差；正文抽取会多一个依赖和内存，也更容易碰到版权问题，先不做。

## 落地记录（任务 41，2026-10-07）
Q41a–h 按推荐确认。
- **表**（41.1）：`feeds`（`tenant_id` 为空 = 内置，带 `builtin_key`；自加源按（租户、地址）唯一；条件请求信息、下次抓取时间、连续失败次数、错误码）、`feed_subscriptions`（内置源没有行 = 订阅，取消才写 `subscribed=false`）、`articles`（(feed, guid) 唯一，正文是纯文本段落，`summary_only`、`license`、`word_count`、`tags`）。内置源登记在 `services/news/sources.py`，启动时同步。迁移 `a982263b9709`。依赖 `feedparser` 6.0.14（BSD-2-Clause，导入约 +9 MB）。
- **抓取与清洗**（41.2）：`fetch.py`（`net_guard` 直连；或走 `FEED_HTTP_PROXY`，Q41h：当前网络下 Global Voices 只能走代理，此时自己跟随跳转、每一跳先查地址，本机 DNS 解析不了的名字交给代理；20 秒、5 MB、最多 3 次跳转）、`parse.py`、`clean.py`（纯文本段落，Q41c）、`rules.py`（第 1 条的规则）。**正文抽取不引入**（Q41d）：只给摘要的条目标 `summary_only`（不到 150 词），阅读页显示摘要和原文链接，不改写。
- **定时任务**（41.3）：`rss_fetch` 每 2 小时，只抓到期且有人读的 feed，最多 4 个并发，每个 feed 单独事务；连续失败 3 次后间隔翻倍，最长 24 小时（Q41f）；超过 90 天的文章不收、并删除（Q41g；任务 42/43 加上改写和阅读记录后要保留有引用的）。
- **接口**（41.4）：`/reading/feeds`（列出、添加、订阅开关、删除自加源）、`/reading/articles`（按订阅、游标分页）。每人最多订阅 20 个自加源（Q41e）；添加新地址先抓一次，抓不到不保存。
- 实抓（2026-10-07）：NASA 10 条留 5，Global Voices 15 条留 12；两个源第二次请求都是 304。测试用手写 fixture，不提交抓来的正文。

## 落地记录（任务 42，2026-10-08）
Q42a–i 按推荐确认（用户授权一律按推荐）。
- **等级与缓存**（Q42a）：目标等级 = 画像 `cefr_level`（没有按 A2），提示词要求写在该级上沿；缓存键（租户、文章、等级）只有 A1–C1 五档，C2 读原文。表 `article_versions`（迁移 `7aeed833bec4`），参数在 `rules.yaml` 的 `reading:`（规则版本 `2026-10-08.1`）。
- **改写**（Q42b、Q42d、Q42e）：`agents/reading_graph.py`，一次 `article_rewrite` 调用写改写稿和 5 道四选一理解题；原文最多 3,000 词；字数超出该级范围 25% 以上重写一次。理解题代码先查依据句在改写稿里、选项不重复，再由 `reading_critic`（走 `exercise_critic` 路由）不看答案自己做；被拒的题 `reading_questions` 重写一轮，最终只留通过的，一道没过也照样给文章。critic 只看改写稿不看原文。
- **词表**（Q42c）：代码算，不让模型列（`services/reading/glossary.py`）：ECDICT 词频排名超过该级阈值的词，跳过专名，最多 15 个；另存超纲词占比供评估。
- **触发**（Q42f、Q42g）：打开时现写（`POST /reading/articles/{id}/version` + 轮询）；定时任务 `article_prerewrite` 每 2 小时为订阅者的等级预写各源最近 3 天最新 2 篇，查租户后台每日上限，学习者开关 `article_prerewrite`（默认开）。失败的版本后台不重试，留给学习者打开时重试。
- **许可**（Q42i）：只有 `public_domain`、`cc_by` 改写；学习者自加源（`unknown`）显示原文。
- **保留**（Q42h，修订 Q41g）：改写版本是缓存，随文章删除，不阻止 90 天清理；任务 43 的阅读记录才保留文章。

## 落地记录（任务 43，2026-10-08）
Q43a–j 按推荐确认（用户授权一律按推荐）。
- **阅读记录**（Q43a）：表 `reading_sessions`（迁移 `ab322160460f`），同一人同一篇一条，再打开接着用；不记查过哪些词。90 天清理跳过有阅读记录的文章（Q42h 的另一半）。
- **理解题**（Q43b、Q43c）：一次交全部答案，代码判，答案判完才下发；只有第一次作答计分，每题一步 Elo 更新 `skill_estimates.reading`（题目难度 = 版本等级的锚点，猜中下限 0.25），不记语法证据。阅读能力和语法同一刻度，看板和学习者模型按 `placement.grammar.cefr_cutpoints` 换算成 CEFR 位置。提交时锁住阅读记录行，防止并发重复计分。
- **文中标记**（Q43d）：到期词（`learning` 且 `due` ≤ 现在 + `learn_ahead_minutes`，和复习页口径一致）黄色高亮，词表里的词虚下划线，任何词都弹单词气泡；到期词由后端按这篇文字算。
- **不改写的文章**（Q43e）：只有摘要的显示摘要和“去原网站阅读”；`unknown` 许可和 C2 显示全文、有气泡和到期词，没有理解题。
- **页面**（Q43f、Q43g）：`/reading` 列表（新到旧、来源 chips、“已为你改写 / 只有摘要 / 读过”标记、管理来源抽屉），不做话题筛选；`/reading/[id]` 打开时取我的版本，生成中每 2 秒轮询并先显示原文，失败可重试，可切换“你的等级 / 原文”，出处行按许可写。
- **reading_coach**（Q43h、Q43i）：阅读页“问私教”新开会话（`conversations.article_id`，purpose `reading`），按固定信号路由，不进分类器；每轮带我等级的改写版（没有就原文前 1,500 词），提示词标明文章是资料不是指令；不带工具，用量记 `reading_coach`，活动记 `reading_context`。
- **E2E**（Q43j）：`frontend/e2e/reading.spec.ts` 两条，假模型补 `ArticleRewrite`、`QuestionSet`、`QuestionReviews`。
