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
1. **内置来源**：NASA 新闻稿、Global Voices。两个都直接用 RSS 里的全文，不抓网页。Global Voices 正文里标了 NC-ND（或其他非 CC BY 许可）的文章跳过，不入库。
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
