# 0022 · 语法知识图谱存 Postgres，不引入 Neo4j

- **状态**：已采纳（2026-10-02，任务 30；D2）
- **日期**：2026-10-02
- **影响**：取代 ADR 0001 和 PLAN 里“Neo4j 存语法知识图谱”的部分；删除 compose 的 `neo4j` profile、`neo4j-data` 卷和 `.env.example` 里的 `NEO4J_*`；新增 `kc_edges` 表和 `adaptive/graph.py`；`grammar.yaml` 加 `confusable_with`。

## 背景
PLAN 原计划用 Neo4j Community 存语法知识图谱，再叠加用户的 `MASTERY` 边做 GraphRAG。P1 实际落地后：

- 语法 KC 是 `backend/app/adaptive/kc/grammar.yaml` 里的 119 个静态条目（ADR 0010），约 109 个有 `prerequisites`，`catalog.py` 在加载时校验无环。图的规模是百级节点、几百条边，增长靠人工审核，不会很快变大。
- 诊断要的查询是“某个薄弱 KC 的前置链（深度 ≤ 3）+ 易混 KC，以及它们各自的掌握度和最近证据”。掌握度（`kc_mastery`）和证据（`kc_evidence`）都在 Postgres 里。
- Neo4j 要多占约 1 GB 内存（compose 里 `mem_limit: 1g`、堆 512 MB），线上是低配服务器；而且图和学习者数据分在两个库，每次诊断都要跨库拼数据，用户删除数据时也要两边删。

## 决定
1. **真相源仍是 `grammar.yaml`**：已有 `prerequisites`；新增 `confusable_with`（同类易错 / 易混的 KC），由 LLM 起草、用户审核后入库（同任务 6 的做法）。`catalog.py` 继续校验：引用的 KC 都存在，`prerequisites` 无环，`confusable_with` 对称存储时去重。
2. **存储**：`kc_edges`（`from_kc`、`to_kc`、`kind` ∈ `prerequisite` / `confusable`，主键三列），后端启动时（以及 `make kc-sync`）从 YAML 全量同步：在一个事务里删掉再写入。全局只读数据，不按租户隔离。
3. **查询**：递归 CTE 查前置链（深度上限放 `rules.yaml`，默认 3），直接 join 学习者的 `kc_mastery` 和最近的 `kc_evidence`。所有图查询封装在 `backend/app/adaptive/graph.py`，调用方不写 SQL；以后要换图数据库（例如 Apache AGE 或 Neo4j）只改这一层。
4. **GraphRAG 的含义**：给定薄弱 KC → 前置链 + 易混 KC → 各自的掌握度和最近证据（原句 / 改正）→ 拼成诊断的上下文。这一步是确定的图遍历，不做向量召回；P2 的语法资料就是 `grammar.yaml` 里的说明和常见错误，量不大。
5. **清理**：删除 compose 的 `neo4j` 服务和 `neo4j-data` 卷、`.env.example` 的 `NEO4J_*`，同步 CLAUDE.md 和 PLAN 的目录说明。

## 取舍
- 放弃了 Neo4j 的可视化（Browser）和 Cypher 的表达力。对百级节点、深度 ≤ 3 的查询，递归 CTE 足够，而且能和掌握度在一个查询里 join；要给学习者看图，前端自己画就行。
- 以后如果加入大量语法资料做向量召回，或者 KC 增长到上万，再评估 Apache AGE（Postgres 扩展，不多一个服务）或独立图数据库；`graph.py` 这一层就是为此留的。
- 已经用 `docker compose --profile neo4j` 起过 Neo4j 的本地环境会留下一个孤立的 `neo4j-data` 卷，需要手动 `docker volume rm`。P0–P1 没有任何代码写过它，没有数据损失。
