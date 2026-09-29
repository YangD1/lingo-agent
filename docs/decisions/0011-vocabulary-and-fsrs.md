# 0011 · 词库与背词调度：ECDICT 子集 + py-fsrs

- **状态**：已采纳（2026-09-29，`docs/plans/P1-mvp.md` Q7、Q9 按推荐确认）
- **日期**：2026-09-29
- **影响**：新增依赖 `fsrs`；新增 `words`、`word_books`、`user_word_book`、`user_cards`、`review_logs` 表和 `make vocab-import`。

## 背景
PLAN 定了“词表做骨架 + LLM 做个性化”、调度用 FSRS。落地前要确定：导入多少词、FSRS 自己写还是用库、线上低配服务器能不能承受。

核实结果（2026-09-29）：
- **ECDICT**（MIT）：`ecdict.csv` 66 MB，约 77 万条，其中绝大多数是短语和生僻词；仓库里的 `ecdict.mini.csv` 只是 50 行左右的样例，没有现成的小子集。考试标签词数：中考 1603、高考 3677、CET4 3849、CET6 5407、考研 4801、雅思 5040、托福 6974、GRE 7504；牛津 3000 核心词 3461 个，柯林斯星级词 13633 个。数据最近几年基本没有更新，内容稳定。
- **py-fsrs**（PyPI `fsrs` 6.3.2，2026-08，MIT，维护活跃）：实现 FSRS-6；核心调度只依赖 `typing-extensions`，参数优化器是可选 extra（会拉 torch / numpy / pandas）。`Card` / `ReviewLog` 都有 `to_dict()` / `from_dict()`，字段可以直接映射成表的列。时间必须是 UTC。

## 决定
1. **导入子集**：有考试标签、或牛津核心词、或柯林斯星级、或 `bnc` / `frq` 排名前 3 万的词，预计 2–3 万条。只导入要用的列。
2. **导入脚本**：`make vocab-import` 下载 CSV 到 `data/`（不进仓库），流式逐行过滤，用 `COPY` 写入 `words`，可重复执行。测试用仓库里几十行的小 CSV。
3. **词书是按 tag 的虚拟分组**，不复制词表；进度 = 该 tag 下 `user_cards` 为 known / learning / review 的比例。
4. **调度用 py-fsrs 的 `Scheduler`**（不装 `[optimizer]`），`desired_retention=0.9`；FSRS 状态展开成 `user_cards` 的列，而不是存 JSON，这样“今天到期”可以直接走索引查询。每次复习写 `review_logs`（含前后状态），以后要按用户拟合参数时有数据。
5. **熟词筛选**：“认识”的词标记为 `known`，不进复习队列；不为它们伪造 FSRS 状态。
6. **每日队列**：到期复习 → 生词本新词 → 词书新词（按词频）；新词每日上限默认 15。
7. P1 只做翻卡片（回想 → 自评四档）。发音用浏览器的 `speechSynthesis`，不经过后端。

## 取舍
- 子集会漏掉一些用户在阅读或对话里遇到的低频词。自动收词时查不到的词先丢弃；如果以后这种情况多，可以改为按需从完整 CSV 补导单个词，或者改为全量导入。
- 没有参数优化器，所有用户共用 FSRS 默认参数。有了足够的 `review_logs` 后，可以离线跑优化器，再按用户保存参数（P4）。
- 词库不按租户隔离（全局只读数据）；租户自己的生词、卡片都按 user_id 隔离。
