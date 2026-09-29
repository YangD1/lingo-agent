# 会话交接日志

> 新记录追加在**最上方**。每条包括：做了什么 / 未完成（精确到文件或函数）/ 下一步 / 踩坑。

---

## 2026-09-29 · P1b 任务 8b：agent 活动公示（ADR 0013 §3）

- **做了什么**：拆成 8b.1–8b.6，用户确认了三点：记忆只存引用、隐藏开关存 localStorage、后台结果用短轮询。完成：`agent_activities` 表和 `app/activity/`；`load_context` 记活动并通过 SSE `activity` 事件推送，`done` 带 `turn_id`；反思记 `reflect_memory` / `grammar_tagging` / `summarize`（失败记 failed，没配模型记 skipped）；`GET /conversations/{id}/activity`（记忆解析成当前内容、KC 名称、`pending`）；前端每条回复下的“私教做了什么”（收起一行 / 展开明细）、`done` 后 60 秒内轮询、设置页“显示”开关；E2E。明细见看板。
- **未完成**：无。明细里的 `/learner` 链接等任务 9 做出页面后再加（`frontend/src/components/chat/turn-activity.tsx` 的 grammar_tagging 分支）。
- **下一步**：任务 9：学习者模型接口 + `/learner` 页面。开工前拆子任务、和用户确认。
- **踩坑**：
  - `streamChat` 原来遇到第一个非 token 事件就结束，加了 `activity` 事件后必须改成读到 done / error 才停。
  - 活动摘要放在消息 `<li>` 里，会破坏 E2E 对整条消息的 `toHaveText` 和正则匹配。现在气泡是 `li > [data-slot=message]`，E2E 的消息选择器都指向它；以后在消息下面加东西，也放在气泡外面。
  - 新建会话时回复可能在会话 id 切换之前就结束，所以 `use-activity` 不在切换时清定时器，而是按会话 id 丢弃过期结果。
  - React lint 不允许在 effect 里直接 setState，所以状态里记着它属于哪个会话，切换时视为空状态。
  - 测试里 `expire_all()` 之后再读 ORM 对象的属性会触发同步懒加载报错（MissingGreenlet），要先把 id 取到局部变量。
  - `mypy` 只检查 `app`（与 CI 一致），`tests/` 里有几个历史遗留的类型错误，不在 CI 检查范围内。
  - 无头 Chromium 没有中文字体，截图里中文是方块，和应用无关。

---

## 2026-09-29 · P1b 任务 8：反思打标 → 证据 → 掌握度；ADR 0013

- **做了什么**：用户要求记住 agent 工具调用的特性、公示 agent 用到的工具 / MCP：写了 ADR 0013（工具调用规范 + 界面公示）、`docs/agent-tools.md`（公开清单）、CLAUDE.md 约束一条、长期记忆一条；界面公示排为任务 8b（每条回复下默认收起、可展开，设置里可隐藏）。任务 8 完成，明细见看板。
- **未完成**：无。
- **下一步**：任务 8b：活动记录表（每步一行：类型、名称、状态、耗时、面向学习者的白名单摘要）；`load_context`、反思（记忆增删改、错误打标）写入活动；SSE 推送对话中的步骤；前端回复完成后再取一次后台结果；设置里可隐藏；更新 `docs/agent-tools.md`。开工前拆子任务、和用户确认。
- **踩坑**：反思输入改了格式（`Learner [u1]:`），E2E 假模型按 `^Learner: ` 匹配，会让记忆 E2E 静默失效，已改。`record_chat_evidence` 的删除用 `RETURNING kc_id`，这样被删掉证据的 KC 也会重算。语音消息的转写文本同样会被打标，prompt 已排除标点和大小写，但转写错误（同音词）仍可能被当成语法错误，任务 8b 公示出来后观察。同一事务里 `now()` 相同，证据按 (created_at, id) 排序重放。

---

## 2026-09-29 · P1b 任务 7：规则文件、BKT、Elo、学习者模型表

- **做了什么**：任务 7 完成。用户选定：BKT 先验按等级差给值、严重度三级（low 不计入）、`skill_estimates` 存 attempts；题目难度由 LLM 按维度打分给先验、Elo 按作答校准。用户要求以后方便改规则 → ADR 0012：规则集中在 `app/adaptive/rules.yaml`（带版本号）；`mistakes` 表改为只追加的 `kc_evidence`，掌握度由证据重放得出，`kc_mastery` 记 `rules_version`。代码在 `app/adaptive/{rules,bkt,elo}.py`，迁移 `612ac223409b`。提交 `8e1796f` 及本次提交。
- **未完成**：无。
- **下一步**：任务 8：反思 schema 加 `mistakes`（kc_id、error_type、severity、original、correction、l1_transfer）和 `used_correctly`；KC 清单渲染进反思 prompt 的固定前缀（id + description + common_errors）；非法 kc_id 丢弃；写入 `kc_evidence`（message_id 用学习者消息 id，要防止反思重试时重复写入）；按受影响的 KC 重放并写回 `kc_mastery`；`rules_version` 变化时的重建时机（建议读取时发现版本不符就重建该用户）。开工前先拆子任务、和用户确认。
- **踩坑**：YAML 行内映射 `{offset: 0.4, description: ..., e.g. ...}` 里的逗号会把描述拆成多个键（extra="forbid" 抓到了），描述要加引号。BKT 连续答对后浮点数会算出正好 1.0，之后永远降不下来，结果要限制在 [1e-4, 1-1e-4]。测试里 commit 之后 ORM 对象过期，再读 `user.id` 会触发 MissingGreenlet，要在 commit 前取出来。

---

## 2026-09-29 · P1b 任务 6 完成：KC 清单审核

- **做了什么**：用户不逐条审核，授权按英语教师的专业标准自审。按“一个 KC 只对应一种技能、一种错误只归一个 KC”重构清单，得到 119 个 KC，改动明细见看板 6.3。ADR 0010 §1 补上规则和 `error_type` 五类枚举。新增例句唯一性测试。
- **未完成**：无。`.claude/state/kc-review.html` 审核页已经过时（还是 118 个的初稿），没用了。
- **下一步**：任务 7：BKT / Elo 纯函数（`app/adaptive/`，只用标准库）+ `kc_mastery`、`mistakes`、`skill_estimates` 表和迁移。开工前先拆子任务、和用户确认。
- **踩坑**：初稿里同一种错误常常挂在好几个 KC 下（如“He can speaks”同时在第三人称和 can 下、逗号连写同时在三个 KC 下），打标时会把证据摊薄；以后改清单时，`test_shipped_error_examples_have_one_owner` 只能查出重复的引号例句，语义上的重叠还要人看。

---

## 2026-09-29 · P1b 任务 6：语法 KC 清单初稿与加载校验

- **做了什么**：任务 6 拆成 6.1–6.3，三个设计问题用户都选了推荐项（`error_type` 用全局五类枚举；清单只收语法；初稿在会话里直接起草）。6.1 `app/adaptive/kc/catalog.py` + lifespan 启动时加载 + 15 个单测；6.2 `app/adaptive/kc/grammar.yaml` 118 个 KC。提交 `c1bf757`。pytest 437、ruff、mypy 通过。
- **未完成**：6.3 用户审核。审核页是本地文件 `.claude/state/kc-review.html`（数据由 `.claude/state/kcs.json` 嵌入，模板 `kc-review.tpl.html`；清单改了之后要重新导出并生成）。没能发布成 Artifact：本会话用 `ANTHROPIC_AUTH_TOKEN` 鉴权，Artifact 需要 claude.ai 登录。
- **下一步**：用户把审核意见（页面“复制审核意见”生成的文本）贴回来 → 改 `grammar.yaml` → 跑 `tests/unit/test_kc_catalog.py` → 提交，任务 6 标 `[x]`；然后任务 7（BKT / Elo 纯函数 + 三张表）。反思 prompt 用的 KC 清单渲染（id + description）留到任务 8 再写。
- **踩坑**：KC 清单用列表而不是以 id 为键的映射，因为 YAML 会静默覆盖重复键，唯一性校验就失效了。

---

## 2026-09-29 · P1a 任务 5：记忆/画像接口与 `/memory` 页面

- **做了什么**：任务 5 完成，P1a（长期记忆）全部完成。后端 `app/api/memory.py` + `tests/integration/test_memory_api.py`（提交 `e975e59`）；前端 `/memory` 页面（`src/components/memory/{memory-app,profile-section,memory-list-section}.tsx`、`src/lib/profile.ts`）、导航、`proxy.ts` 匹配 `/memory`、设置页 `RouteSection` 加入 `reflect`；中英文案；E2E 假模型支持记忆（`e2e/fake_llm.py` 的 `reflection`、`remembered_facts`）和 `e2e/memory.spec.ts`。详见看板完成记录。
- **未完成**：无。没有在设置页加 embedding（`embedding/memory`）路由编辑：计划里任务 5 只要求 `reflect`，而且 `RouteSection` 目前只按对话/语音筛选模型列表，要支持 embedding 需要在 `model-catalog.ts` 加 embedding 分类。没配时按 YAML 的 embedding 默认路由，检索退化为按时间，不影响使用。是否要加由用户决定。
- **下一步**：任务 6（语法 KC 清单：LLM 起草 → 用户审核 + 加载校验），开工前先拆任务、和用户确认。
- **踩坑**：E2E 里不要在回复还在流式输出时离开页面：请求被取消（`llm_usage` 记为 `CancelledError`），这一轮不算完成，也就不会触发反思。等回复完整显示、“发送”按钮回来再跳转。`page.waitForResponse(...).finished()` 对这个 SSE 请求不可靠（会一直等），用界面状态判断。上次会话因为请求体超过 32 MB 中断，改动都还在工作区，接着做即可；本机 zsh 的 `pnpm` 是 nvm 懒加载函数，在 Bash 工具里会无限递归，要用 `~/.nvm/versions/node/v24.14.0/bin/pnpm` 并把该目录加进 PATH。

---

## 2026-09-29 · P1 规划：阶段计划与 ADR 草稿

- **做了什么**：写了 `docs/plans/P1-mvp.md`（Demo 脚本、四个子阶段 P1a 记忆 / P1b 学习者模型 / P1c 背单词 / P1d 入学测、依赖、设计、17 个任务、待确认的 Q1–Q10）和 ADR 0009（长期记忆）、0010（学习者模型）、0011（词库与 FSRS）草稿，状态都是“提议”。看板的 P1 部分已拆好任务。没有改代码。
- **调研结论**（2026-09-29 查 PyPI / GitHub）：py-fsrs 6.3.2 实现 FSRS-6，核心只依赖 typing-extensions，不装 `[optimizer]`；ECDICT 77 万条、66 MB，没有现成小子集，标签词数写在 ADR 0011；LangGraph `AsyncPostgresStore` 在 langgraph-checkpoint-postgres 3.1 里，但语义索引在创建时固定 embedding 函数和维度，和租户各自配置 embedding 冲突，所以推荐自建 `memories` 表；LangMem 自 2025-10 的 0.0.30 后没有新版本，不引入；pyBKT 依赖 numpy / sklearn / pandas，BKT 和 Elo 自己写。
- **确认结果**：用户确认 Q1–Q10 全部按推荐；ADR 0009–0011 改为已采纳，PLAN 已同步。用户同时追加需求“个人能力看板（图表）+ AI 建议 + 直达学习”，写成计划 §7.5 和子阶段 P1e（任务 17–19，原 Demo 实测顺延为 20），Q11–Q14 待确认。
- **未完成**：Q11–Q14（看板图表组合、建议生成方式、首页、图表库）等用户确认。
- **任务 0 完成**：11C 第 3、4 条（详见看板完成记录）。
- **Q11–Q14**：用户确认全部按推荐。
- **任务 2 完成**：画像表、记忆表、记忆服务层（详见看板完成记录）。
- **任务 3 完成**：`load_context` 节点，学习者上下文走 `UntrackedValue` 通道，不进 checkpoint（详见看板和 ADR 0009 落地记录）。
- **任务 4 完成**：后台反思（详见看板完成记录和 ADR 0009 落地记录）。
- **下一步**：任务 5，记忆/画像接口（`app/api/memory.py`：GET/PATCH 画像、记忆列表、PATCH/DELETE 单条、清空）+ 前端 `/memory` 页面（画像表单、事实列表可编辑删除、会话摘要列表）+ 设置页路由编辑器加入 `reflect`（`frontend/src/components/settings/route-section.tsx` 的 `RouteTask`）+ E2E：聊天 → 记忆出现 → 删除 → 新会话不再使用（假模型需要能返回一条记忆，可以按消息内容决定）。
- **踩坑**：工具函数别以 `test_` 开头（`test_clip` 被测试模块导入后会被 pytest 当成测试收集），已改名 `silent_clip`。pgvector 的 alembic autogenerate 会写出 `pgvector.sqlalchemy.vector.VECTOR()` 却不加 import，要手动改成 `from pgvector.sqlalchemy import Vector`。LangGraph 状态里有不想持久化的中间值时用 `Annotated[T, UntrackedValue(T)]`；图的 input/output schema 要另设为 `MessagesState`，否则调用方的类型要求带上这个字段。

---

## 2026-09-29 · 11B 实测：语音转写接入硅基流动

- **做了什么**：用户实测 11B。看图（中转站 gpt-6-sol）和 PDF 提取正常；语音一路排查：中转站没有 `/audio/transcriptions`（404）→ 本地 speaches（要 `PROVIDER_ALLOW_PRIVATE_NETWORKS=true`，容器里地址是 `http://asr:8000/v1`）→ 第一段录音 -60 dB 几乎静音，Whisper 编出一串“ლ”，是麦克风问题 → 想换 Groq，发现 Groq 屏蔽大陆 IP（直连 403，经代理 401），后端又有意不走代理 → 新增硅基流动预设（11B.7），用户实测中英文都转写正确。顺带修了测试会读开发者 `.env` 的问题。CI 全绿。
- **未完成**：11C 五个体验问题（看板里有），待用户决定做不做。
- **下一步**：**用户已选 P1**（11C 暂缓）。新会话先读 `docs/PLAN.md` §二·五、§三、§四 P1，参照 `docs/plans/P0-skeleton.md` 写 P1 阶段计划和 ADR，拆任务后和用户确认。原先的备选是：先做 11C，还是直接规划 P1（Supervisor 主图、长期记忆、FSRS 背单词、CEFR 入学测、自适应引擎第一版）。P1 开工前要先写阶段计划（参照 `docs/plans/P0-skeleton.md`）和相关 ADR，拆任务写进看板，确认后再动手。
- **踩坑**：国外模型 API 的地区屏蔽只在直连时出现，开发机上经代理测试会漏掉，要从后端容器里测（`httpx`，`trust_env=False`）。Whisper 对静音会编造文字，判断转写质量前先用 `ffmpeg -af volumedetect` 看音量。本机的 gh 装在 `~/.local/bin`，已登录。

---

## 2026-09-29 · 任务 13 README

- **做了什么**：`README.md`（英文）+ `README.zh-CN.md`（中文），顶部互相链接，带 CI 徽章；如实写 P0 能做什么 / 还没做什么，Docker 快速开始、模型配置（三个任务、本机模型服务与 SSRF 开关、可选本地语音转写）、本地开发、mermaid 架构简图 + 目录说明 + ADR 链接、部署注意事项、贡献。界面名称按 i18n 文案核对（中文界面是“对话”“语音转文字”）。`CLAUDE.md` 补了“常用命令”。从 GitHub 新 clone，用独立的 compose 项目名照 README 从零跑通（详见 PROGRESS 13.4）。
- **未完成**：无。11B（附件）仍待用户用真实模型实测。
- **下一步**：用户实测 11B；之后确认 P0 收尾，按 PLAN 规划 P1（开工前先拆任务写进看板）。
- **踩坑**：compose 文件固定了 `name: lingo-agent`，同一台机器上再 clone 一份直接 `make up` 会接管原来的容器和数据卷，验证时要设 `COMPOSE_PROJECT_NAME` 并换端口。zsh 里 `echo ======` 会报 `= not found`（`=word` 会被展开成命令路径）。

---

## 2026-09-29 · 任务 12 推送到 GitHub，修 CI

- **做了什么**：用户确认保留提交邮箱和文档里的环境细节后，添加 remote `git@github.com:YangD1/lingo-agent.git`（公开仓库）并推送 main。第一次 CI：frontend、docker 通过，backend、e2e 在 Set up job 失败（`astral-sh/setup-uv@v10` 不存在），改为 `@v10.2.0`。第二次运行只有 backend 的 pytest 失败；本地去掉代理变量、TZ=UTC 重跑，复现出测试在做真实 DNS 解析（`test_chat_attachments.py` 没有 DNS 桩），改为在 `tests/conftest.py` 全局加 `public_dns`。但第三次仍失败；装 gh（官方二进制放到 `~/.local/bin`）并登录后读日志，真正原因是 `test_chat_attachments.py` 的 `not_ready` 用例在和后台处理任务赛跑，已改成确定性写法。
- **未完成**：第二次 CI 运行的结果；backend 和 e2e 的测试步骤在 GitHub 上还没真正跑过。
- **下一步**：CI 全绿后把任务 12 标 `[x]`，然后做任务 13 README。
- **踩坑**：CI 失败先读日志再猜——`gh run view <id> --log-failed`。全局 autouse fixture 不要依赖 `monkeypatch`，否则会改变各模块 fixture 的撤销顺序（`_clear_caches` 报 `cache_clear` 不存在）。本机 gh 不可用，但仓库公开，可以不带认证调用 `api.github.com/repos/.../actions/runs` 和 `check-runs/<job id>/annotations` 查状态和失败原因（日志下载需要认证）。setup-uv 从 v8 起没有浮动的主版本标签，要写完整版本号。

---

## 2026-09-29 · 任务 12 GitHub Actions CI

- **做了什么**：`.github/workflows/ci.yml`，四个 job（backend / frontend / docker / e2e），每次推送 main 和每个 PR 都跑（用户选 A）；`make ci`；P0 计划 §10 已同步；`e2e/run_backend.py` 的数据库地址改为从 `E2E_ADMIN_DB` 推导。actionlint 通过；在新 clone 的仓库和全新数据库上模拟了 backend、frontend、e2e 三个 job，全部通过。
- **未完成**：GitHub 上的实际运行。仓库还没有 remote，要用户建仓库并推送。第一次运行时注意：Action 版本号来自子代理查询；GHA 的 docker 缓存第一次是冷的；e2e 在 GitHub runner 上的耗时还不知道。
- **下一步**：任务 13 README（英文 + zh-CN）+ CLAUDE.md 的“常用命令”。
- **踩坑**：zsh 里 `pnpm` 是懒加载 nvm 的函数，设了 PATH 也会递归调用，要先 `unset -f pnpm`；`timeout` 后面不能接 shell 内建的 `command`。

---

## 2026-09-29 · 11B.6 附件 E2E、speaches、全栈冒烟（11B 完成）

- **做了什么**：
  - 假模型支持看图识别（function calling）、回复中说明看到几张图、`/audio/transcriptions`。
  - E2E `attachments.spec.ts` 6 个用例，完整套件 21 个全部通过；录音、canvas 压缩、粘贴 / 拖拽这次在真实 Chromium 里验证了。
  - compose profile `asr`（speaches）+ `make asr-up/asr-down`，真实语音转写测试通过。
  - 重建镜像，全栈冒烟通过。细节见看板 11B.6a–d。
- **未完成**：用户实测。用户要在 `.env` 里设 `PROVIDER_ALLOW_PRIVATE_NETWORKS=true`（compose 里的后端要访问 `http://asr:8000/v1`），访问不了 huggingface.co 时再设 `ASR_HF_ENDPOINT=https://hf-mirror.com`，然后 `make up`。
- **下一步**：任务 12 GitHub Actions CI（backend / frontend / docker build）。E2E 进 CI 时注意：Playwright 的 webServer 用 `uv run --project ../backend` 拉起假模型和后端，需要 postgres 服务；附件用例用 Chromium 假麦克风参数。
- **踩坑**：
  - 容器用不了宿主机只监听 127.0.0.1 的代理（Clash 7890），HF 只能走镜像站。
  - 旧 backend 镜像配新 YAML 会因为 `extra_forbidden` 一直重启：改了 YAML 结构后要重建镜像。
  - Playwright 拿不到由 Blob 组成的 multipart 请求体。
  - eslint 的 hooks 规则会把 `use*` 名字的 E2E 辅助函数当成 React hook。
  - zsh 不会对 `$C` 这类变量做分词，复杂的 curl 流程改用 Python 脚本写。

---

## 2026-09-29 · 11B.5 前端附件输入与展示

- **做了什么**：11B.5a–e 全部完成（细节见看板 11B.5 的“完成记录”）。前端：附件按钮 / 粘贴 / 拖拽 / 录音，附件卡片（上传中、识别中带页数进度、失败可重试、查看和修改识别结果、移除），附件未就绪时不能发送，消息里显示图片 / 音频 / 文档；设置页可以编辑 chat、vision、asr 三个路由；中英文案和 17 个新错误码。typecheck、lint、build、Vitest 93、Playwright 15 全部通过。
- **未完成**：录音、canvas 压缩、粘贴和拖拽只在 jsdom 里测过逻辑，还没有在真实浏览器里跑过。
- **下一步**：11B.6：`e2e/fake_llm.py` 支持看图回显（能看到 image 块就回显）和 `/audio/transcriptions`；E2E 用 `data-testid="attachment-input"` 的隐藏 file input 调 `setInputFiles` 上传；覆盖图片、文档（含扫描版 PDF）、语音文件（录音可以用 Chromium 的 `--use-fake-device-for-media-stream` + `--use-fake-ui-for-media-stream`）、未配置 vision 时的“去设置”、修改识别结果；compose 加 `asr` profile（speaches）并实测内存；重建镜像交给用户实测。
- **踩坑**：设置页有多张路由卡片后，E2E 里按名字查找按钮会命中多个元素，要先用 `getByTestId("route-<task>")` 限定范围。
- **注意**：上次会话因为请求超过 32MB 而中断（对话里累积了太多图片）。做 11B.6 的界面验证时尽量少截图，或者截小图。

---

## 2026-09-29 · 11B.4 附件接入对话

- **做了什么**：上次会话写完 11B.4 代码和测试后因请求过大中断，本次修复测试（残留的一行乱码；录制假模型的 `calls` 字段被 pydantic 复制导致记录为空）并全量验证：pytest 367、ruff、mypy(app) 通过。细节见看板 11B.4。
- **未完成**：无（11B.4 已完成）。`tests/unit/test_vision_and_asr.py:129` 有之前就存在的 mypy 报错（`make lint` 只检查 app，不影响）。
- **下一步**：11B.5 前端（附件按钮 / 粘贴 / 拖拽 / 录音、附件卡片轮询、消息内展示、设置页 vision/asr 路由、中英文案）。发送接口：`POST /conversations/{id}/messages` 的 body 为 `{content, attachment_ids}`；错误码 404 `attachment_not_found`，409 `no_vision_model` / `attachment_not_ready` / `attachment_sent`，422 `invalid_attachments` / `too_many_images`；历史接口每条消息带 `attachments`（AttachmentOut）。
- **踩坑**：pydantic 模型（包括 BaseChatModel 子类）的 `list` 字段会在校验时复制，想共享可变对象要用 `Any`。

---

## 2026-09-29 · 11B.3 附件派生文本

- **做了什么**：vision 路由（只认显式配置）、`asr` 一节 + `get_asr()`、图片 / 语音 / PDF（含扫描页）/ DOCX 的处理函数，以及对应测试。细节见看板 11B.3。
- **未完成**：11B.4 对话接入：
  - `app/api/chat.py` 的 `MessageIn` 加 `attachment_ids`，在 `start_turn` 里校验：附件属于同一会话、状态为 ready、还没发送；单条消息最多 5 个，其中图片最多 4 张；正文为空时必须有语音附件。
  - `app/chat/turn.py` 由后端生成 HumanMessage 的 id，并写入 `attachments.message_id`。
  - `app/agents/chat_graph.py` 的 tutor 节点组装附件：通过 ChatContext 传一个附件读取器，按消息 id 查附件；当前轮带图片时改用 `vision` 路由。
  - `get_history` 返回附件信息。
- **下一步**：11B.4 → 11B.5 前端 → 11B.6 E2E、speaches compose、重建镜像。
- **踩坑**：
  - 手写 PDF 时，`io.BytesIO(初始内容)` 的写入位置在 0，后续写入会覆盖文件头。
  - alembic 的 `op.drop_constraint` / `create_check_constraint` 也会套用 naming convention，名字要包在 `op.f()` 里，否则会变成 `ck_表_ck_表_列`。
  - TaskGroup 抛出的是 ExceptionGroup，处理器只认 `ProcessingFailed`，所以要先从组里取出来。
  - OpenAI 已推荐改用 `gpt-transcribe`，`whisper-1` 等将在 2027-02 下线（第三方站点报道，OpenAI 文档确认了推荐模型）。

---

## 2026-09-29 · 11A 收尾，11B.1 设计，11B.2 附件存储与接口

- **做了什么**：
  - 用户实测 11A 通过。
  - 11B 设计：ADR 0008 已采纳（图片 + 语音 + 文档（含扫描版 PDF），“两者结合”，PostgreSQL bytea，进程内后台处理 + 轮询），PLAN 已同步。
  - 11B.2 后端附件：`backend/app/attachments/`（sniff、images、processor、handlers、service）+ `app/api/attachments.py` + 迁移；app.state 上有 `attachment_processor`（`main.py` 的 `init_state` 创建，lifespan 启动时执行 `fail_interrupted`，退出时 `stop`）；测试夹具同步。
- **未完成**：11B.3 派生文本。在 `app/attachments/handlers.py` 的 `default_handlers()` 里加 image / audio / pdf / docx 处理函数，需要：provider 层的 `llm.vision` 路由 + `ImageReading`，`asr` 一节 + `get_asr()`，`llm_usage.audio_seconds`，pypdfium2 + python-docx。处理函数运行在后台任务里，需要**自己加载租户的 provider 上下文**（`load_provider_context(session, job.tenant_id)`），调用看图模型时要持有 `processor.vision_slots`，所以处理函数需要能拿到 processor（可以用闭包或工厂函数注入）。
- **下一步**：11B.3 → 11B.4 对话接入 → 11B.5 前端 → 11B.6 E2E 与部署。
- **踩坑**：
  - `deferred(mapped_column(LargeBinary))` 会让 autogenerate 生成 nullable=True，要显式写 `nullable=False`。
  - MP3 帧同步只看 11 位的话，UTF-16 BOM（FF FE）也能匹配上，要加 Layer III 判断。
  - Pillow `draft()` 要求返回的尺寸在**两条边**上都不小于请求值，要按原图比例算请求尺寸，不能传正方形。
  - 测内存峰值要在新进程里测，否则前面造数据时的峰值会掩盖结果。
  - 迁移还没在开发库（:3000 那套）上执行：11B.6 重建镜像时，后端启动会自动执行。

---

## 2026-09-28 · 11A.8 聊天消息渲染 Markdown

- **做了什么**：用户反馈模型回复里的 `**加粗**` 原样显示。原因是 `message-list.tsx` 直接输出纯文本。新增 `frontend/src/components/chat/markdown.tsx`（react-markdown + remark-gfm + remark-cjk-friendly/parseOnly），只用于 assistant 消息；单测 5 个 + E2E 1 个；前端镜像已重建。
- **未完成**：11A.6 仍在等用户用中转站实测。用户提出“用户消息支持多模态输入”，已记为看板任务 11B，需要先设计（PLAN + ADR：消息内容结构、上传存储、模型能力路由），还没开始。
- **下一步**：等用户确认 11A.6 → 11B 设计 或 任务 12 CI（由用户定顺序）。
- **踩坑**：
  - react-markdown 会给自定义组件传 `node` prop，直接 `{...props}` 展开会变成 DOM 属性，要先去掉（`markdown.tsx` 的 `styled()`）。
  - 回复里有列表后，E2E 的 `locator("li")` 会把列表项也算成消息，改用 `:scope > li`。
  - 用户消息仍需 `whitespace-pre-wrap`；assistant 消息不能加，否则块元素之间的 `\n` 会多出空行。

---

## 2026-09-28 · P0 任务 11A.4–11A.5（前端：建连接选默认模型、路由下拉编辑）

- **做了什么**（每项单独提交）：
  - 11A.4 连接卡片：新建连接后自动拉取模型列表，预选推荐模型，可搜索，失败时显示厂商原因并可手填；测试按钮直接测框里的模型。新增 `ui/autocomplete.tsx`（Base UI **Autocomplete**，值就是输入框的文字）、`lib/models.ts`（+单测）；`fake_llm.py` 加 `/v1/models`。
  - 11A.5 `chat-route-section.tsx` 重写：显示实际生效的链和来源；编辑改为每行“连接下拉 + 模型搜索”，可增删、调顺序。`settings/model-catalog.ts` 共用。E2E 改为不设路由就能聊天，新增拉取失败的用例。
- **未完成**：11A.6 收尾——全量 `make test`/`make lint`，重建镜像 `make up`，请用户用自己的中转站实测。
- **下一步**：11A.6，然后任务 12 CI。
- **踩坑**：
  - Base UI 弹层打开时会把页面其余部分设为 `aria-hidden`，Playwright 按角色定位会找不到按钮：手填后先按 Tab 关掉弹层。
  - Playwright 对整个 `list` 用数组形式的 `toHaveText`，只有列表里恰好一项时才成立；多项要对 `getByRole("listitem")` 断言。
  - 前端没有装 prettier，`pnpm exec prettier` 会找不到命令（之前一次还卡住了）；格式只靠 eslint。
  - Playwright 的 `reuseExistingServer` 会复用端口上已有的旧 fake_llm（没有 `/v1/models`），跑 E2E 前先 `fuser 8100/tcp 8101/tcp 3100/tcp` 确认端口空闲。

---
## 2026-09-28 · P0 任务 11（docker-compose 全栈、.env.example、Makefile）→ 完成

- **做了什么**（每个子任务单独提交）：
  - 11.1 `backend/Dockerfile`：启动时迁移、非 root、HEALTHCHECK。
  - 11.2 `frontend/Dockerfile`：standalone；`BACKEND_URL` 构建时和运行时都注入；`pnpm start` 改为 `scripts/start-standalone.mjs`，E2E 也跑它；限制 `next build` 的 worker 数和堆内存。
  - 11.3 `docker-compose.yml`：新增 backend、frontend 服务；只有前端对外，其余都只绑 127.0.0.1；neo4j、redis 放进 profile。
  - 11.4 `Makefile`（`make help` 列出全部目标）+ `.env.example`。
  - 11.5 独立 compose 项目从零走完 Demo，包括降级、重启后数据还在、密钥轮换、`host.docker.internal`。细节见看板和 P0 计划 §16。
- **未完成**：无。仍待用户手动：在设置页填真实 key 做一次冒烟（可以直接 `make env && make up` 后在 :3000 上做）。
- **下一步**：任务 12 GitHub Actions CI。按 P0 计划 §10：backend job（postgres service，`uv sync --locked` → ruff → format check → mypy → pytest）、frontend job（lint、typecheck、Vitest、build）、E2E job（需要 postgres + uv + pnpm + chromium）、docker job（`docker compose build`）。
- **踩坑**：
  - **本机做重构建会把 Windows 拖崩**：两次 docker 构建耗尽了 Windows 的提交内存（vmmemWSL 约 10GB + MuMu 模拟器 7.7GB，上限 39.7GB），WSL 和模拟器一起崩溃。WSL 内部的 cgroup 上限和看门狗都没用，因为 vmmem 会随 Linux 页缓存一起涨。用户已设 `.wslconfig`：`memory=8GB`、`swap=4GB`、`autoMemoryReclaim=dropCache`，页面文件改为系统管理。重构建前用 `powershell.exe` 查一下 Windows 可用提交内存（`Win32_OperatingSystem.FreeVirtualMemory`）。证据在 Windows 事件日志 Resource-Exhaustion-Detector 2004。
  - 崩溃时 pnpm 缓存里留下了写到一半的文件，报 `ERR_PNPM_CMD_SHIM_PARSE_MANIFEST`；用 `docker buildx du --filter type=exec.cachemount` 找到它，再用 `docker buildx prune --filter id=…` 只清这一个。
  - 不要写 `# syntax=docker/dockerfile:1`：BuildKit 解析它时直连 Docker Hub，本机代理环境下会超时。`docker manifest inspect` 同理；`docker pull` 走守护进程的代理，是通的。
  - uv 0.11.8 没有 `…-python3.12-bookworm-slim` 组合镜像，改用 `COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv`。
  - pnpm 12 不支持 `-s`；zsh 不会把 `$VAR` 按空格拆成多个参数，多步 shell 流程写成 bash 脚本再跑。
  - `e2e/fake_llm.py` 只监听 127.0.0.1，容器里访问不到；冒烟时在 docker 网络里用 `uvicorn.run(fake_llm.app, host='0.0.0.0')` 启动它。

---
## 2026-09-28 · P0 任务 10.5–10.8（聊天页、设置页、E2E、收尾）→ 任务 10 完成

- **做了什么**（每项单独提交）：
  - 10.5 聊天页：`/chat?c=<id>`（History API，新建会话不重新挂载）；会话延迟创建，开流前被拒绝就删掉空会话并把文字还回输入框；`no_llm_configured` 引导去设置；停止生成标注“未保存”。核心在 `components/chat/use-chat-session.ts`。
  - 10.6 设置页 `components/settings/`：连接（预设/自定义、测试、替换 key、删除）、chat 路由（fallback 链，可恢复默认）、用量表（7/30/90 天，手动刷新）。新增 `ui/native-select.tsx`。
  - 10.7 E2E 共 11 个（auth 3、chat 3、settings 2、i18n 3），本次补了“登录后在应用内切换语言”。
  - 10.8 全量检查 + 经 Next 代理的 curl 全栈冒烟（SSE 逐块到达）；P0 计划 §8/§10/任务表已同步。
- **未完成**：无（任务 10 已 `[x]`）。待用户手动做一次真实 key 冒烟（设置页填 key → 聊天）。
- **下一步**：任务 11 docker-compose 全栈 + `.env.example` + Makefile（`gen-key` / `rotate-credentials`）。前端 Dockerfile 要把 `BACKEND_URL` 作为 **build arg**（rewrites 在构建时确定），并用 `output: "standalone"`（`next.config.ts` 现在还没加）。
- **踩坑**：
  - Next 的 rewrites 目标在 `next build` 时写死：手动起生产服务冒烟时忘了带 `BACKEND_URL` 构建，结果代理指向了 :8000。
  - 在 `( … &)` 子 shell 里调 `pnpm` 会命中 zsh profile 里的 nvm 懒加载函数（`_load_nvm` not found），要用绝对路径 `~/.nvm/versions/node/v24.14.0/bin/pnpm`。
  - shadcn base-nova 的 `CardTitle` 是 `div` 不是 heading，E2E 用 `getByText` 定位。
  - WSL 里的 headless chromium 没有中文字体，中文截图显示方框，只是环境问题。
  - 后端历史接口里 assistant 消息的 id 是 LangChain 的 run id（`lc_run--…`），不是 UUID；前端只把它当不透明的 key，暂不影响。

---
## 2026-09-28 · P0 任务 10.1–10.4（前端脚手架、i18n、API/SSE 客户端、鉴权）

- **做了什么**（每项单独提交）：
  - 10.1 Next 16.3.6 脚手架 + shadcn（base-nova）+ Vitest + Playwright。**实测 SSE 经过 Next rewrites 时会被 gzip 缓冲**（dev 和 start 都会），后端 `start_turn` 追加 `Cache-Control: no-transform` 后修复（`fix(chat)`），不需要走备选方案；abort 能经过代理传到后端。
  - 按用户决定，把后端**所有**错误统一为 `{detail:{code,message}}`（`app/api/errors.py`，包括全局 handler），ADR 0003 §3。
  - 10.2 i18n：next-intl，语言存在 cookie 里，不做 URL 前缀（ADR 0006）。和原计划不同：语言协商放在 `request.ts` 里，proxy 只负责鉴权。
  - 10.3 `lib/api.ts`、`lib/sse.ts`（async generator）。
  - 10.4 登录和注册页、`proxy.ts`（乐观检查）+ `(app)` 布局用 `/auth/me` 做权威校验 + `/session-expired`（防止重定向死循环）。E2E 基础设施：`frontend/e2e/run_backend.py` + Playwright 双 webServer。
- **未完成**：10.5 聊天页（`src/app/(app)/chat/page.tsx` 现在是占位）、10.6 设置页（`(app)/settings/page.tsx` 占位）、10.7 剩下的部分（`e2e/fake_llm.py` 和聊天/设置的 E2E 用例）、10.8 收尾。
- **下一步**：10.5 聊天页，用 `streamChat()`；409 `no_llm_configured` 引导去 /settings。
- **踩坑**：
  - 在 Bash 工具里用 `pkill -f <模式>` 或 `pgrep -f` 会匹配到**当前 shell 自己的命令行**，把自己杀掉（exit 144）。改用 `fuser -k <port>/tcp`。
  - FastAPI 的 SSE 接口体在响应头发出之后才运行，所以响应头只能在依赖里设置；而且是 `raw.extend` 追加，不是覆盖。
  - Next 16.3 自带文档写的是 `unstable_doesProxyMatch`，但实际导出的只有 `unstable_doesMiddlewareMatch`。
  - `PageProps<"/login">` 这类路由类型要先运行 `next typegen`，所以 typecheck 脚本改成了 `next typegen && tsc --noEmit`。
  - Next 的路由播报器（`__next-route-announcer__`）也是 `role=alert`，E2E 要把定位范围限定在表单内。
  - `pnpm add` 遇到带构建脚本的新依赖时，会往 `pnpm-workspace.yaml` 的 allowBuilds 里写占位值 `set this to true or false`，要手动改成 true 或 false。
  - 在一个测试文件里 import 另一个 `*.test.ts`，会把那个文件的测试重复注册一遍；公共的测试辅助函数放在 `src/test/`。
  - `frontend/` 目录下的 .py 文件要用 `--config ../backend/pyproject.toml` 跑 ruff。
  - 这个环境访问不了 GitHub 和 next-intl.dev，查文档就直接读 `node_modules` 里的 README、类型定义和源码。

---


## 2026-09-28 · P0 任务 9 完成（9.4 冒烟与两个断开相关的修复）

- **做了什么**：
  - 真实 uvicorn + 本地假 OpenAI 兼容服务（逐字慢速流式输出，支持 `stream_options.include_usage`）+ curl 端到端冒烟。走的是真实的 openai SDK、SSRF 防护过的传输层、stream_usage 和用量回调。验证了：注册 → 未配模型时返回 409 → 建连接和路由 → 流式回复（usage 42/16）→ 客户端中途断开 → 立即重发返回 200 → 历史 → `/tenant/usage`。
  - **发现并修复两个 bug**（各自单独提交，都带修复前失败的回归测试）：
    1. `fix(usage)`：被取消的调用漏记。`UsageRecorder` 改为同步 handler，并设 `run_inline=True`。
    2. `fix(chat)`：客户端断开后，**上游模型仍然生成完整回复**（租户白付费）。`stream_reply` 改为在独立 task 里跑图，断开时显式 cancel，并在 shield 的 scope 里等它清理完；tutor 节点改用 astream 再合并 chunk，让取消能通知到回调。
  - 同步了 ADR 0003（改用 fastapi.sse、开流前返回的 404 和 409 错误码、断开的实现细节）、ADR 0005（被取消的调用怎么记的两个条件）、P0 计划（sse-starlette 标为不再使用、§6.3）。
  - 全部 208 个测试通过，ruff 和 mypy strict 都干净。
- **未完成**：无。Next rewrites 转发 SSE 时是否会缓冲，留到任务 10 验证（ADR 0003 里的已知风险）。
- **下一步**：任务 10 frontend（Next 16 + shadcn、登录和注册、聊天页、模型设置页含用量表、SSE 客户端、proxy.ts）。开工前先拆分子任务，和用户确认。
- **踩坑**：
  - **anyio 的取消是电平触发的**：在已取消的 scope 里，每一个会挂起的 await 都会再被取消一次。第三方库 finally 里的清理 await（比如 LangGraph 取消节点 task 的那部分）也会被打断，所以要自己管理子 task 的生命周期。普通 asyncio 的 `task.cancel()` 是边沿触发的，没有这个问题。进程内对照实验的脚本思路：anyio.move_on_after 与 task.cancel() 各跑一次，看模型是否中止。
  - `ainvoke` 被取消时不会调用 `on_llm_error`（内部 gather 直接抛出），只有 `astream` 会。以后可能被用户取消的模型调用都用 astream。
  - pydantic 模型的 `list[str]` 字段会在校验时被复制，测试想观察的可变对象要声明成 `Any`。
  - 冒烟和测试共用 `lingo_test`：跑一次全量测试就会 TRUNCATE 冒烟数据，冒烟要在测试之后重新注册。
  - zsh 不会对未加引号的变量做分词，`-H $J` 这种写法会把整个 header 当成一个参数，要写成 `-H "$CT"`。
  - 清空一个正被别的进程写入的日志（`: > file`）后，文件前面会变成一段空字节，grep 会把它当二进制文件跳过，要用 `strings` 看。

---

## 2026-09-28 · P0 任务 9 进行中（9.3 完成）

- **做了什么**：
  - `app/chat/turn.py`：`TokenEvent` / `DoneEvent` / `ErrorEvent`、`title_from`（空白压缩后取前 40 个字符）、`begin_turn`（设标题并刷新 updated_at，然后 **commit**，流式期间不占数据库事务）、`stream_reply`（只转发 tutor 节点的 AIMessageChunk；累加 usage；异常时发 `llm_unavailable`，不泄漏厂商错误文本；metadata 带 user_id，tags 为 `["chat"]`）。
  - `app/chat/locks.py`：`ConversationLocks`（进程内非阻塞锁），在 `create_app` 里挂到 `app.state`。
  - `app/api/chat.py`：`start_turn` yield 依赖（依次做：归属检查返回 404 → 加载 ctx 并解析 chat 路由，失败返回 409 `no_llm_configured` → 加锁，失败返回 409 `conversation_busy` → begin_turn → yield，finally 释放锁）；`send_message` 用 `EventSourceResponse` 输出 SSE，事件名即 event 字段，data 为 JSON。
  - 新增 `tests/integration/test_chat_send.py`（10 个用例）：token 之后是 done、done.message_id 和历史里的 id 一致、标题和排序、llm_usage 记到 user 和会话、主模型在出第一个 token 前失败时切到备用模型（端到端 usage 两行）、中途失败发 error 事件且只保留用户消息、失败后锁已释放可以重试、未配模型返回 409 且不入库、会话忙返回 409、越权返回 404、长度校验返回 422。
  - 全部 202 个测试通过，ruff 和 mypy 都干净。
- **下一步**：9.4，用真实 uvicorn + curl 冒烟（包括客户端中途断开后锁会释放），同步 ADR 0003 / P0 计划（sse-starlette 换成 fastapi.sse、409 的错误码）。
- **踩坑**：
  - **FastAPI 内置 SSE 在执行接口体之前就已经发出 200 响应头**（接口体在 producer task 里跑，见 `fastapi/routing.py` 约第 553–612 行），所以 404 和 409 必须在依赖里抛。yield 依赖默认挂在 request 级的 exit stack 上，流结束或断开后才退出，锁放在这里一定会被释放。
  - 模型按 `(tenant, task, version)` 缓存，测试里中途换假模型后要 `llm.reset_caches()`。
  - `/auth/me` 的返回结构是 `{user: {...}, tenant: {...}}`。

---

## 2026-09-28 · P0 任务 9 进行中（9.2 完成）

- **做了什么**：
  - `app/chat/service.py`：`ConversationNotFoundError`（不存在和不是自己的会话不作区分）、`thread_config`、`list_conversations`（按 updated_at 倒序）、`create_conversation`、`get_owned_conversation`、`to_chat_messages`（只返回 user 和 assistant 消息，内容用 `.text` 拍平成纯文本）、`get_history`、`delete_conversation`（先删 checkpoint，再删行）。
  - `app/api/chat.py`：`GET/POST /conversations`、`GET /conversations/{id}/messages`、`DELETE /conversations/{id}`；访问别人的会话一律返回 404。
  - `app/deps.py` 新增 `ChatGraphDep`。
  - conftest 拆出 `app` fixture（带真实的 Postgres checkpointer），`client` 基于它建。
  - 新增 `tests/integration/test_chat_api.py`，共 7 个用例。全部 192 个测试通过，ruff 和 mypy 都干净。
- **下一步**：9.3 发消息 SSE。
- **踩坑**：删除用户时，会话行会级联删掉，但 **checkpoint 里的消息会变成孤儿**（和“个人租户变孤儿”是同一类问题）。以后做“注销账号”时，要先逐个会话调 `adelete_thread`。

---

## 2026-09-28 · P0 任务 9 进行中（9.1 完成）

- **已确认的决定**：SSE 用 FastAPI 0.141 内置的 `fastapi.sse.EventSourceResponse`（支持 POST，自带 keepalive），不再引入 sse-starlette；没配模型时在开流前返回 409 `no_llm_configured`；同一会话正在生成时再发送返回 409 `conversation_busy`，用进程内锁，多 worker 时改用 advisory lock，放到 P4。
- **做了什么（9.1）**：
  - `app/agents/chat_graph.py`：`ChatContext(providers)`、`tutor` 节点、`build_chat_graph(checkpointer)`、`ChatGraph` 类型别名。system prompt 每次调用时拼在最前面，不存进会话，所以改提示词对老会话也生效。
  - `app/prompts/__init__.py`（`load_prompt`）和 `tutor_system.md`。
  - `app/db/migrate.py` 新增 `create_checkpointer_pool`（autocommit、dict_row、prepare_threshold=0）。settings 和 `.env.example` 新增 `CHECKPOINT_POOL_MAX_SIZE=4`。
  - lifespan 负责打开连接池，建好 `app.state.chat_graph`，关闭时关连接池；checkpoint 表仍由 migrate 创建。
  - conftest 在每个测试后同时 TRUNCATE checkpoint 表（保留 `checkpoint_migrations`）。
  - `tests/integration/test_chat_graph.py` 共 4 个用例：多轮对话按 thread 累积；system prompt 发给模型但不入库；token 来自 tutor 节点；**checkpoint 三张表（包括解码后的 blob）里都没有 key**。
  - 全部 185 个测试通过，ruff 和 mypy 都干净；用真实 lifespan 冒烟通过。
- **下一步**：9.2 会话 CRUD（`app/chat/service.py`、`app/api/chat.py`）。
- **踩坑**：
  - **反向验证**：把 key 放进 `configurable` 后，“key 不入 checkpoint”的测试会失败，因为 LangGraph 会把 configurable 写进 checkpoint 的 metadata。这印证了 ADR 0004 的判断：ctx 只能走运行时 context。
  - PreToolUse 钩子会拦截 `sk-live-...` 这种形状的测试值，改用不像厂商 key 格式的标记串。
  - `graph.astream` 的返回类型覆盖了所有 stream_mode，在 messages 模式下要用 isinstance 把 metadata 收窄成 dict，mypy 才能通过。
  - 用户要求按关键节点提交，方便事后 review 和学习。任务 1–8 是事后按主题拆成 8 个提交补上的，中间的提交不保证能单独运行；从 9.1 开始，每个子任务单独提交一次。

---

## 2026-09-28 · P0 任务 8 完成（第 5 步 llm_usage）

- **做了什么**：
  - `app/usage/recorder.py`：
    - `UsageLabels`、`UsageRecord`、`UsageRecorder`：`on_chat_model_start` 按 run_id 记下开始时间和从 metadata 取到的 id；`on_llm_end` 从 `usage_metadata` 取 token 数；`on_llm_error` 只记异常类名。
    - `set_usage_sink`、`submit_usage`、`make_recorder`。
    - 方案按用户确认的 A：缺少 `user_id` 或 `conversation_id` 时照常记录，该列留空；会话 id 也可以从 LangGraph 的 `thread_id` 取。
  - `app/usage/writer.py`：`UsageWriter`（`submit`、`start`、`stop`、`flush`），攒满或定时批量写库；队列满时丢弃并计数；写库失败时 writer 继续运行。
  - `app/usage/service.py`：`summarize_usage`；`app/api/usage.py`：`GET /tenant/usage`。
  - `llm.py`：`build_chat_model` 新增 `callbacks` 参数，默认 `stream_usage=True`；`get_chat_models` 给每个模型挂 recorder，并按链中位置标 `is_fallback`。`CallParams` 白名单加了 `stream_usage`。
  - 连接的 `/test` 也会记录用量（task 为 `connection_test`）。
  - `require_tenant_manager` 和 `Manager` 从 `api/providers.py` 移到 `app/deps.py`。
  - lifespan 负责启动 writer、安装 sink；关闭时先卸载 sink，再在 5 秒内把队列写完。
  - ADR 0005 A 节：状态改为 `status` 加 `is_fallback`，补了实现细节。
  - 新增 `tests/unit/test_usage_recorder.py`（15 个用例）和 `tests/integration/test_usage.py`（10 个用例）。全部 181 个测试通过，用量相关测试连跑 3 次都稳定；ruff 和 mypy strict（app 和 tests）都干净。另外用脚本在测试库上跑了真实 lifespan，确认关闭时会把队列写完。
- **未完成**：无。Makefile 的 `rotate-credentials` 和 `gen-key` 按原计划放在任务 11。
- **下一步**：任务 9，对话图。调用时要传 `config={"configurable": {"thread_id": str(conversation.id)}, "metadata": {"user_id": str(user.id)}}`，用量记录就能拿到这两个 id。
- **踩坑**：
  - P0 里每个用户都是自己个人租户的 owner，而 `get_current_tenant` 按“owner 身份加个人租户”查找，所以通过 HTTP 走不到 403 这条路径。如果把角色降成 member，接口会直接返回 500（找不到个人租户）。目前的测试是直接调用 `require_tenant_manager`。做组织租户时，要改 `get_current_tenant` 的查找方式。
  - 用系统代理或设置了 `no_proxy` 时，langchain-openai 会打印一条“injected a custom httpx transport”警告。**这是误报**：它在检查我们是否自带 client 之前就打印了（`langchain_openai/chat_models/base.py:1496`），实际用的仍然是我们防护过的 client，已有测试覆盖。
  - 测试里 monkeypatch 了 `get_providers_config` 后，不要在测试函数体里调 `llm.reset_caches()`，因为这时它已被替换成普通函数，没有 `cache_clear`。应该用 autouse fixture，在 monkeypatch 还原之后再清理。

---

## 2026-09-28 · P0 任务 8 进行中（第 4 步完成，补记）

- **说明**：上一会话写完第 4 步后没来得及写交接记录，本条是新会话按代码实际状态补记的。
- **做了什么**：
  - `app/credentials/service.py`：连接的增删改查（`create_connection` / `update_connection` / `delete_connection`、`key_hint`），保存时用 `validate_base_url` 检查 URL；`verify_connection`；路由覆盖的 `list_route_overrides` / `put_route` / `delete_route`、`known_tasks`。
  - `app/api/providers.py`：`/provider-presets`、`/tenant/connections`（CRUD 与 `/{id}/test`）、`/tenant/routes`（GET、PUT、DELETE `/{section}/{task}`）。除 presets 外都要求 owner/admin（`require_tenant_manager`）。
  - `app/credentials/rotate.py`：`rotate_credentials`，以及命令行 `python -m app.credentials.rotate`。Makefile 入口放到任务 11。
  - `tests/integration/test_model_settings_api.py` 共 14 个用例。全部 156 个测试通过，ruff 和 mypy strict 都干净（本会话复核过）。
- **下一步**：第 5 步 llm_usage，方案待用户确认。
- **踩坑（本会话发现）**：因为我们显式传了 `base_url` 和 `http_async_client`，ChatOpenAI **不会自动开启 `stream_usage`**（`langchain_openai/chat_models/base.py:1431-1450`），流式调用拿不到 token 数。第 5 步要显式处理。

---

## 2026-09-28 · P0 任务 8 进行中（第 3 步完成）

- **做了什么**：
  - YAML 改为 `presets`（kind、base_url、label、推荐模型）加默认路由，已经不含任何 key。
  - `config.py` 改写：新增 `PresetSpec`、`ConnectionSpec`、`TenantProviderContext`、`ResolvedModel`、`route_for`、`resolve_route(config, ctx, section, task)`、`check_embedding_route`。
  - `errors.py` 新增 `NoModelConfiguredError`，带 `code` 字段（`no_llm_configured` / `no_embedding_configured`）。
  - `cache.py` 实现 `TTLCache`。
  - `tenant.py` 实现 `load_provider_context`：解密 key；已停用或解密失败的连接直接跳过；version 由各行的 updated_at 算指纹。
  - `llm.py` 改写：`build_chat_model` 注入防护过的 httpx2 client，显式传 base_url；anthropic 改用 `GuardedChatAnthropic`；`get_llm`、`get_structured_llm`、`get_chat_model`、`get_chat_models` 都改成 `(ctx, task)` 参数，缓存键为 `(tenant, task, version)`。
  - `embedding.py` 同样改成 ctx 版本。
  - lifespan 启动时不再校验路由，改为调用 `get_providers_config()`，只检查 YAML 结构。
  - 新迁移 `fe27d411cdcc`：`provider_connections.base_url` 改为 NOT NULL。
  - 新增 `app/db/schema_filter.py`，让 Alembic 忽略 LangGraph 的表；测试库现在也会建 checkpoint 表。
  - 共 131 个测试全部通过。
- **下一步**：第 4 步是连接和路由的 CRUD 接口，外加 `/provider-presets`、`/test` 和 `make rotate-credentials`；第 5 步是 llm_usage。
- **踩坑**：**Alembic autogenerate 差点生成 DROP LangGraph checkpoint 表的迁移**（会删掉所有对话历史）。已经用 `include_object` 过滤，并加了回归测试 `test_autogenerate_never_drops_langgraph_tables`。以后每次 autogenerate 后都要审一遍生成的迁移文件。

---

## 2026-09-28 · P0 任务 8 进行中（第 1–2 步完成）

- **做了什么**：
  - 第 1 步：`app/credentials/crypto.py` 实现了 `Keyring`（encrypt、decrypt、needs_rotation）、`parse_keyring`、`get_keyring`、`connection_aad`、`generate_key_entry`，以及命令行 `python -m app.credentials.crypto gen-key`。settings 新增 `credentials_encryption_keys` 和 `provider_allow_private_networks`；lifespan 启动时调 `get_keyring()`，没有主密钥就拒绝启动（放在 lifespan 而不是 Settings 校验里，这样迁移命令不需要密钥）。conftest 里设置了测试专用的密钥。
  - 第 2 步：`app/providers/net_guard.py` 实现了 `is_forbidden_ip`（专门处理了 IPv4-mapped 和 NAT64）、`resolve`（测试可替换）、`validate_base_url`、`GuardedNetworkBackend`、`make_async_http_client`（替换连接池的 `_network_backend`；不跟随重定向；trust_env=False）、`make_blocked_sync_client`。`app/providers/clients.py` 实现了 `GuardedChatAnthropic`，覆盖 `_async_client`，同步调用直接抛错。
  - 新增 `tests/unit/test_crypto.py` 和 `tests/unit/test_net_guard.py`。
- **未完成**：第 3–5 步：YAML 改为“预设 + 默认路由”并加上 TenantProviderContext 和缓存；连接和路由的 CRUD 以及 /test；llm_usage。
- **下一步**：第 3 步。`build_chat_model` 需要：对 openai 和 deepseek 传 `http_async_client=make_async_http_client(...)` 和 `http_client=make_blocked_sync_client()`；anthropic 改用 `GuardedChatAnthropic(...).with_http_client(...)`；**base_url 必须显式传入**，否则 SDK 会去读 OPENAI_BASE_URL / ANTHROPIC_BASE_URL 环境变量。
- **踩坑**：
  - **openai 3.19 和 anthropic 1.8 这两个 SDK 已经从 httpx 换成了 `httpx2` / `httpcore2`（API 完全相同的分支），并会对 http_client 做 isinstance 检查，传原版 httpx 的 client 会被拒收**。所以防护代码必须基于 httpx2，已加为显式依赖，也有测试 `test_sdks_accept_our_http_client_type` 覆盖。
  - Python 的 `ipaddress` 把 NAT64 地址（64:ff9b::/96）判为 is_global=True，即使它里面嵌的是 127.0.0.1。
  - ruff 的 ASYNC109 规则在实现 httpcore 接口时属于误报，已加带原因的 noqa。

---

## 2026-09-28 · P0 任务 7（鉴权）

- **做了什么**：
  - `app/auth/security.py`：`hash_password`、`verify_password`（返回 `(ok, new_hash)`，参数升级后会给出新哈希）、`burn_verify_time`、`create_access_token`、`decode_access_token`（限定算法为 HS256，要求 sub、exp、iat 三个声明，并检查 type 为 access）。
  - `app/auth/service.py`：`register_user`（同一事务里建 user、个人 tenant 和 owner 成员关系；邮箱是否重复以唯一索引为准）、`authenticate`、`get_personal_tenant`、`normalize_email`。
  - `app/api/auth.py`：register、login、token、logout、me 五个接口。
  - `app/deps.py`：`AUTH_COOKIE`、`get_current_user`（先看 Bearer，再看 cookie）、`get_current_tenant`，以及 `SessionDep`、`SettingsDep`、`CurrentUser`、`CurrentTenant` 几个类型别名。
  - settings：prod 下 JWT 密钥至少 32 字节；新增 `cookie_secure` 属性。
  - 新增 `tests/unit/test_security.py` 和 `tests/integration/test_auth_api.py`，conftest 里加了 `client` fixture，并设置了测试用的 JWT_SECRET。共 63 个测试全部通过，重复执行也稳定；ruff 和 mypy strict 都干净。
  - 用真实 uvicorn 和 curl 走了一遍完整流程：readyz、注册、cookie、me（cookie 和 Bearer 两种方式）、登出。ADR 0003 补了实现细节和 CSRF 的分析。
- **未完成**：无。
- **下一步**：任务 8（最大的一项），建议按这个顺序拆开做：
  1. `app/credentials/crypto.py`（AES-GCM，AAD 用 `tenant_id:connection_id`，密钥 id 加轮换）和 `make gen-key`；
  2. `app/providers/net_guard.py`（保存时检查 URL；连接时用自定义 `httpcore.AsyncNetworkBackend` 检查 IP；ChatAnthropic 子类）；
  3. YAML 改为“预设 + 默认路由”，`config.py` 和 `llm.py` 改成用 `TenantProviderContext`，缓存改成 LRU + TTL，键为 `(tenant_id, task, version)`，删掉启动时的 `validate_llm_routes`；
  4. 连接和路由的 CRUD 接口，以及 `/test`；
  5. `llm_usage` 回调和用量查询接口。
- **踩坑**：
  - conftest 设置了 `JWT_SECRET` 环境变量，依赖默认值的 settings 测试要显式传参。
  - 删除用户时只会级联删掉 tenant_members，**个人租户会变成孤儿**。以后做“注销账号”时要同时删除个人租户（P1 前补上）。
  - `pkill -f` 又杀掉了执行它的 shell，清理命令要分开跑。

---

## 2026-09-28 · P0 任务 6（数据库）

- **做了什么**：
  - compose 加了 postgres（`pgvector/pgvector:pg16`，实际版本 16.15，pgvector 0.8.6），宿主机端口默认 5433；init 脚本会建 `lingo_test` 库。
  - `app/db/`：
    - `base.py`：命名约定、`TimestampMixin`。
    - `models.py`：Tenant、User、TenantMember、Conversation、ProviderConnection、TenantModelRoute、LLMUsage。
    - `session.py`：`create_engine`、`create_sessionmaker`。
    - `urls.py`：`to_psycopg_conninfo`。
    - `migrate.py`：`alembic_config`、`setup_checkpointer`、`main`。
    - Alembic async 的 `env.py`：支持通过 `config.attributes` 注入 URL 或现成的连接。
    - 首个迁移 `20260928_0849934f390e_initial_schema.py`，包含 vector 扩展。
  - `app/api/health.py` 新增 `/readyz`；`app/deps.py` 新增 `get_session`；`main.py` 新增 `init_state`，lifespan 负责创建和释放 engine。
  - `tests/conftest.py`：`db_engine`（session 级，每次先降级到 base 再升级到 head）、`db_session`（每个测试结束后 TRUNCATE），以及只允许 `_test` 库的安全阀。
  - 新增测试：迁移往返、模型与迁移是否一致、唯一约束、CHECK 约束、级联删除、删除用户后用量记录保留（user_id 置空）、readyz 的 200 和 503。共 45 个测试全部通过，重复执行也稳定；ruff 和 mypy strict 都干净。
  - `python -m app.db.migrate` 已在开发库上跑过，8 张业务表和 4 张 checkpoint 表都已创建。
- **未完成**：`/readyz` 只用 ASGI 测试验证过，没用 uvicorn 实际起服务验证，因为 lifespan 里的 `validate_llm_routes()` 在没有厂商 key 的环境变量时会失败，这个过渡状态要到任务 8 才解决。Makefile 放在任务 11。
- **下一步**：任务 7（鉴权）：`uv add` pyjwt 和 `pwdlib[argon2]`；写 `app/auth/security.py`（`hash_password`、`verify_password`、`create_token`、`decode_token`）、`app/auth/service.py`（`register_user` 在同一个事务里建 user、个人 tenant 和 owner 成员关系；`authenticate`）、`app/api/auth.py`（register、login、logout、me，cookie 加 Bearer）；`deps.py` 加 `get_current_user` 和 `get_current_tenant`。
- **踩坑**：
  - 本机 5432 端口被别的项目的容器 `docker-db-1` 占着，不要去动它，本项目用 5433。
  - Alembic 的 post_write_hooks 必须先跑 format 再跑 check，否则会误报 E501。
  - 在已经运行的事件循环里跑 Alembic，要用 `conn.run_sync(run_alembic, ...)` 并通过 `config.attributes["connection"]` 传入连接，不能调用 `asyncio.run`。
  - `alembic init` 不支持 `-q` 参数。

---

## 2026-09-28 · P0 任务 5（可选 OTel tracing）

- **做了什么**：
  - `app/settings.py` 新增 `otel_tracing_enabled`（默认 False）、`otel_exporter_otlp_endpoint`、`otel_service_name`。
  - `app/observability.py`：`setup_tracing(settings, span_processor=None)` 和 `shutdown_tracing(provider)`。TracerProvider 显式传给 LangChainInstrumentor，不修改 OTel 的全局 provider。lifespan 里接好了初始化和关闭。
  - `docker-compose.yml` 首次创建，目前只有 phoenix 服务（profile `observability`，镜像 `version-20.16.0`，mem_limit 1g）。
  - `tests/unit/test_observability.py`：用内存 exporter 验证 LangGraph 根图、节点和模型调用都会生成 span、带上 metadata、属于同一条 trace。
  - 手动端到端验证：真实 OTLP 导出到 Phoenix，用 REST API 能查回三个 span。测试共 36 个全部通过；ruff 和 mypy 都干净。
- **未完成**：Makefile 还没写（任务 11），目前启动 Phoenix 的命令是 `docker compose --profile observability up -d`。
- **下一步**：任务 6：在 compose 里加 postgres（pgvector/pgvector:pg16）；`uv add` sqlalchemy[asyncio]、alembic、psycopg[binary,pool]；写 `app/db/{base,session,models}.py` 和 Alembic async 迁移，建 users、tenants、tenant_members、conversations、provider_connections、tenant_model_routes、llm_usage 七张表；实现 `/readyz`。
- **踩坑**：
  - `docker manifest inspect` 在这台机器上总是失败，要确认镜像 tag 是否存在，直接 `docker pull`。Phoenix 的 tag 格式是 `version-X.Y.Z`，镜像约 1.5GB。
  - 在 backend 目录外跑脚本时需要 `PYTHONPATH=.`。
  - OpenInference 的实现方式是包装 `BaseCallbackManager.__init__`，是全局 monkeypatch。测试结束后必须调用 `shutdown_tracing` 撤销，否则会影响后面的测试。

---

## 2026-09-28 · 设计变更：可观测性去 LangSmith；任务 4 完成

- **做了什么**：
  - 用户确认：语音 key 同样由租户配置；不用 LangSmith（它是闭源 SaaS，自托管需要企业版授权），采用 A+B 方案。
  - 写了 ADR 0005：A 是自建 `llm_usage` 用量表，租户可见；B 是可选的 OTel tracing，默认关闭，dev 用本地 Phoenix。
  - ADR 0004 改为“已采纳”。ADR 0002 被取代的部分用删除线标出；ADR 0001 也加了指向新 ADR 的说明。
  - 同步了 PLAN.md、CLAUDE.md、README 和 P0 计划 §14。`.env.example` 重写：只留部署方配置，新增 CREDENTIALS_ENCRYPTION_KEYS、PROVIDER_ALLOW_PRIVATE_NETWORKS、OTEL_*，删除所有厂商 key 和 LANGSMITH_*。
  - conftest 中强制关闭 OTel 和 LangSmith 的上报。
- **未完成**：`config/providers.*.yaml` 仍然带 `api_key_env`，`app/providers/config.py` 仍然从环境变量解析 key，`main.py` 仍在启动时调 `validate_llm_routes()`。这些都在任务 8 统一改。现在服务在没有厂商 key 的环境变量时启动不了，这是预期中的过渡状态。
- **下一步**：任务 5：`uv add` openinference-instrumentation-langchain、opentelemetry-sdk、opentelemetry-exporter-otlp-proto-http；写 `app/observability.py` 的 `setup_tracing(settings)`；compose 里加 phoenix 服务（profile `observability`）；实测 LangGraph 节点能不能产生 span。
- **踩坑**：已核实的许可证：openinference-instrumentation-langchain 0.1.76、opentelemetry-sdk 1.45 和 OTLP HTTP 导出器 1.45 都是 Apache-2.0。Phoenix 服务端是 ELv2，只作为独立容器按需运行。

---

## 2026-09-28 · 设计变更：多租户凭据

- **做了什么**：用户决定：模型厂商的 key 不放在配置里，由租户自己配置。具体是个人租户（预留组织）、只用租户自己的 key、租户可以自定义 base_url、模型和路由，在 P0 做完最小闭环。据此写了 ADR 0004（状态：提议），修订了 `docs/plans/P0-skeleton.md` 的 §11 和 §13，同步了 PLAN.md、CLAUDE.md 和看板（任务重新编号为 1–13）。原来的 3b“真实 key 冒烟”已删除。
- **未完成**：ADR 0004 等用户确认。代码还没改：`app/providers/config.py` 仍有 `api_key_env`，`main.py` 仍在启动时调 `validate_llm_routes()`，`.env.example` 里还有厂商 key。这些都在任务 4 和任务 8 里改。
- **下一步**：用户确认 ADR 0004 后，执行任务 4：ADR 0004 改为“已采纳”，改写 ADR 0002 被取代的部分，YAML 改为“预设 + 默认路由”，从 `.env.example` 删除厂商 key。
- **踩坑**：ChatAnthropic 没有 `http_async_client` 字段，它在私有 cached_property `_async_client` 里自己构造 httpx client；要做 SSRF 防护只能写子类覆盖它。ChatOpenAI 和 ChatDeepSeek 可以直接传 `http_async_client`。httpcore 的 `AsyncConnectionPool` 支持 `network_backend` 参数，可以用它在连接时检查 IP。

---

## 2026-09-28 · P0 任务 3（provider 层）

- **做了什么**：
  - `app/providers/config.py`：`ProvidersConfig`、`RouteSpec`（路由可写成字符串、列表或对象）、`load_providers_config`、`resolve_route`（跳过没有 key 的模型并打 warning；整条链都不可用时抛 `ProviderConfigError`）。
  - `app/providers/llm.py`：`build_chat_model`、`get_chat_models`（有缓存）、`get_llm`、`get_structured_llm`（先给每个模型绑定 schema，再串降级链）、`get_chat_model`、`validate_llm_routes`、`reset_caches`。
  - `app/providers/embedding.py`：`get_embeddings`，只允许单模型、不做降级链。
  - `config/providers.{dev,prod}.yaml`；`.env.example` 新增 APP_ENV、PROVIDERS_CONFIG、DASHSCOPE_API_KEY。
  - `main.py` 的 lifespan 在启动时校验所有 LLM 路由。ADR 0002 补了两条：embedding 不做降级链、embedding 延迟校验。
  - 测试共 34 个，全部通过；ruff 和 mypy strict 都干净。
- **未完成**：3b 真实 key 冒烟测试（需要 `.env`）；YAML 里的模型名（`deepseek-chat`、`claude-sonnet-5`、`gpt-5-mini`、`qwen-plus`）还没用真实 API 核对过。
- **下一步**：用户建好 `.env` 后跑冒烟测试：`cd backend && uv run python -c "import asyncio; from app.providers.llm import get_llm; print(asyncio.run(get_llm('chat').ainvoke('Say hi in 3 words')).content)"`。之后做任务 4（`app/observability.py`）。
- **踩坑**：
  - langchain-core 1.6 在每个流末尾都会多发一个 content 为空的 chunk。任务 7 的 SSE 转发必须过滤掉空 chunk。
  - `with_structured_output` 的类型注解写的是返回 `dict | BaseModel`，所以用 `cast` 标注成具体类型，代码注释里写了原因。
  - 现在服务启动时要求至少有一个 LLM key，没有 `.env` 时 uvicorn 起不来（这是 ADR 0002 规定的行为）。用 ASGITransport 跑测试不会触发 lifespan，不受影响。
  - 用 heredoc 写的 .py 文件不会触发 PostToolUse 的 ruff format 钩子，要手动跑 `ruff format`。

---

## 2026-09-28 · P0 任务 1–2

- **做了什么**：任务 1：写了 ADR 0002（provider 层）和 0003（鉴权与流式），同步修改了 PLAN.md 和 CLAUDE.md 里的配置文件名。任务 2：完成 backend 脚手架，包括 `backend/pyproject.toml`（uv；ruff、mypy strict、pytest 的配置）、`app/settings.py`（`Settings`、`get_settings`；APP_ENV=prod 时如果 JWT_SECRET 还是默认值就拒绝启动；PROVIDERS_CONFIG 用相对路径时按仓库根目录解析）、`app/main.py`（`create_app`、lifespan）、`app/api/health.py`（`/healthz`），另有 6 个测试。ruff、mypy、pytest 全部通过，用 uvicorn 实际起服务、curl `/healthz` 也验证过。
- **未完成**：任务 3 provider 层还没开始写。
- **下一步**：`uv add` langchain、langchain-openai、langchain-anthropic、langchain-deepseek；写 `app/providers/{config,llm,embedding,errors}.py` 和 `config/providers.{dev,prod}.yaml`，再按计划 §10 写单测。
- **踩坑**：`pkill -f` 的匹配模式会连同执行它的 shell 一起匹配上，导致退出码是 144，这个退出码可以忽略。依赖只在用到它的那个任务里 `uv add`，不提前一次性装齐。

---

## 2026-09-28 · P0 详细实施计划

- **做了什么**：写出 `docs/plans/P0-skeleton.md`（依赖版本、目录结构、provider 配置格式与接口、DB/鉴权/SSE 设计、compose、测试与 CI、11 个任务的顺序与验证方式）；PROGRESS.md 的 P0 拆成 11 个任务。依赖版本是当天从 PyPI / npm 查的。
- **未完成**：计划 §12 的 Q1–Q6 等用户确认；还没有写代码。
- **下一步**：~~用户确认后开始任务 1~~ → 已确认（Q1–Q6 全部按推荐），任务 1 完成：ADR 0002（provider 层）、0003（鉴权与流式）已写，PLAN.md / CLAUDE.md 的配置文件名同步为 providers.{dev,prod}.yaml。接下来做任务 2（backend 脚手架）。
- **踩坑**：①`RunnableWithFallbacks.__getattr__` 会把 `bind_tools` / `with_structured_output` 转发到每个 fallback，但要靠 `typing.get_type_hints` 解析返回类型，对部分模型会抛 NameError → provider 层要显式包装。②fallback 流式只在第一个 chunk 前切换模型。③npm 最新 TypeScript 是 7.0，先跟随 create-next-app 的版本。④`langgraph-checkpoint-postgres` 只支持 psycopg3，全项目统一用这个驱动。

---

## 2026-09-28 · 项目立项

- **做了什么**：确认整体方案（docs/PLAN.md）；初始化仓库；建立会话记忆协议（CLAUDE.md、PROGRESS.md、本文件、ADR 0001）。
- **未完成**：还没有写业务代码。
- **下一步**：输出 P0 详细实施计划（目录结构、依赖版本、provider 接口定义、compose 服务配置），确认后开始实现。
- **踩坑**：无。
