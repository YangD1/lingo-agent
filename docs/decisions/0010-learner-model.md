# 0010 · 学习者模型：KC、掌握度与入学测

- **状态**：已采纳（2026-09-29，`docs/plans/P1-mvp.md` Q5、Q6、Q8 按推荐确认）
- **日期**：2026-09-29
- **影响**：新增 `kc_mastery`、`mistakes`、`skill_estimates`、`placement_sessions` 表；新增语法 KC 清单和入学测题库（YAML，进仓库）；PLAN 第二·五节的“BKT 或 Elo”定为两者分工使用。

## 背景
PLAN 的原则是“LLM 负责理解和生成，算法负责记账和调度”：LLM 不直接给掌握度打分，掌握度由算法根据证据更新。P1 要落地的是第一版：把对话里的错误打上知识点（KC）标签，更新掌握度；加上入学测。需要确定：KC 用什么 id、用哪种掌握度模型、入学测的题从哪来。

## 决定

### 1. KC 清单
- **语法 KC** 写在 `backend/app/adaptive/kc/grammar.yaml`：稳定的 id（`g.<snake_case>`）、中英文名、CEFR 等级、前置 KC、常见错误提示。启动时加载并校验（id 唯一、前置 KC 存在、前置等级不高于自身、无环），清单有错就拒绝启动。P2 的 Neo4j 语法图谱沿用同一套 id。
- 内容按 CEFR 等级自己编写，不照抄有版权的清单（如 English Grammar Profile）。初稿由 LLM 起草，人工审核后提交。
- **一个 KC 只对应一种技能，一种错误只归一个 KC**：BKT 假设同一 KC 下的证据测的是同一种能力，同一种错误挂在几个 KC 下，证据就被摊薄。所以多个结构共用的形式规则单独成 KC（`g.modal_forms` 情态动词 + 动词原形、`g.past_participle_forms` 过去分词形式），时态类 KC 只管用法；各 KC 的 `common_errors` 互不重叠（测试检查引号里的例句不在两个 KC 下重复出现）。清单只收语法点，搭配、选词、拼写错误按单词处理。
- **`mistakes.error_type` 用全局五类**：omission / addition / wrong_form / wrong_choice / word_order，跨 KC 可统计；`common_errors` 只是给打标模型的提示，不入库。
- **单词 KC** 为 `w.<lemma>`，对应 `words` 表（ADR 0011）。

### 2. 掌握度：三种模型分工
| 对象 | 模型 | 原因 |
|---|---|---|
| 语法 KC | **BKT**（p_init、p_learn、p_guess、p_slip） | 输出“已学会的概率”，可解释，`≥ 0.95` 视为达标 |
| 学习者能力 / 题目难度（入学测、技能估计） | **Elo**，K 随作答次数衰减：`K(n) = α / (1 + β·n)`（Pelánek 2016） | 同时估计能力和难度，冷启动好，适合自适应选题 |
| 单词 | **FSRS 的可提取性** | 已经有 FSRS 调度，不再单独建模 |

- BKT 参数先用全局默认值（`p_learn=0.1`、`p_guess=0.2`、`p_slip=0.1`，`p_init` 按 KC 等级和学习者等级给），积累数据后离线用 pyBKT 拟合（P4）。运行时的 BKT、Elo 更新自己实现，只用标准库，不引入 numpy / scikit-learn。
- 自由表达中用对（产出证据）用更低的 `p_guess`，因为产出比识别更难靠猜。同一轮对同一 KC 最多算一次观测。

### 3. 证据来源（P1）
- 对话反思（ADR 0009）输出 `mistakes`（kc_id、错误类型、原句、改正、严重度、是否母语迁移）和 `used_correctly`。kc_id 不在清单里的丢弃。
- 入学测的作答。
- P2 起加入练习题、写作批改。

### 4. 入学测
- **词汇量测试**：按 ECDICT 的词频排名分段，每题“认识/不认识”，约 25% 是程序生成的假词（按字母转移概率生成，过滤掉词库里存在的词），按假词误报率校正后估计词汇量。不调 LLM。
- **语法/阅读测试**：四选一，题目来自仓库里的静态题库 `backend/app/adaptive/placement/items.yaml`（约 90 题，A1–C2，每题标 KC 和初始难度），用 Elo 选预估正确率 50%–60% 的题，不确定度足够小或满 20 题结束。题库由 LLM 起草，人工逐题审核后提交。
- **用 LangGraph 子图实现**：`pick_item → ask（interrupt）→ update_estimate → 继续或结束`，靠 checkpointer 支持中途退出再继续。选题和更新是纯函数，单独测试。
- 结果写入 `user_profile.cefr_level`、`skill_estimates`、语法 KC 的 BKT 先验。

## 取舍
- **不用 LLM 现场出入学测题**：入学测决定后续所有难度，题目错一道影响很大；项目约束要求 LLM 出的题必须经过 critic，而 critic 在 P2。静态题库的代价是题量有限、多次重测会遇到重复题；P2 可以用“生成 + critic”扩充题库。
- **P1 的掌握度证据偏向“错误”**：对话里出错容易识别，用对不容易完整识别，`used_correctly` 只会覆盖一部分。所以 P1 的 `p_mastery` 偏保守；P2 有了练习题之后证据才平衡。PLAN 第二·五节第 7 条的“学会”判定（≥3 种题型、跨 ≥2 天）也要到 P2 才能完整实现。
- BKT 不建模遗忘；语法 KC 的长期维持在 P2 接入 FSRS（PLAN 已规划），届时两者的关系再写一份 ADR。
