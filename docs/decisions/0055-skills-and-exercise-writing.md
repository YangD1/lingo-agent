# 0055 · 出题质量：skills 机制与出题 skill，难度不再按分歧拒题，critic 只审题

- **状态**：已采纳（2026-10-18，任务 100；方向和子任务 2026-10-17 用户确认，100.1 基线后补“指令不能给出要考的形式”，2026-10-18 确认）
- **日期**：2026-10-18
- **影响**：修订 ADR 0021 §3 的 Q33a（难度）和 critic 的判定、ADR 0015 / 0013（新工具 `load_skill`）。新增 `backend/app/skills/`（加载器和内置 skill `exercise-writing`）；`exercise_generate` 的输出 schema 去掉 `ratings`，choice4 / cloze 加 `other_fillings`，find_fix 加 `error_kind`；`prompts/exercise_generate.md` 的各题型说明挪进 skill，`prompts/exercise_critic.md` 改成清单；`rules.yaml` 去掉 `practice.critic_max_gap`、升版本；`docs/agent-tools.md`、`features.yaml` 同步。无迁移（`exercises.critic` 是 JSONB，多存一个分差字段）。

## 背景
用户反馈出题会卡住、很慢，要求出题“很丝滑”；先查提示词和题目约束，不靠提高题库补位率。

1. **开发库**（2026-10-17）：critic 审过 42 题、拒 15（36%）。难度分歧 8（其中 6 条只因此）、find_fix 埋了漏词 3、cloze 肯定 / 否定都能填 3、critic 按学习者水平拒 B2 点 2。
2. **sub2api 基线**（任务 100.1，`gpt-6.1-sol`，A1 / B1 / B2 三个新账号，7 套练习 + 3 套过关测验，脚本和原始报告在本地 notes）：
   - 首轮通过 70/85 = 82%。拒 15：**没考到这个点 7**（几乎都是 transform / translate 的指令直接给出了要考的形式：给出副词放哪、给出 bored / boring、给出整个从句开头）、**只因难度分歧 5**、答案不唯一 3（find_fix 漏助动词两段都能改、translate 参考答案用了 have got、transform 要求的开头缺主语）、不自然 1。
   - 难度分歧的 5 条一个模式：目标低于这个语法点的 rubric 下限，出题模型 4 个维度全报最简单（translate 也报 `distractors: weak`），critic 把干扰项评高一档，差 0.8 被拒。重写之后题目没变好，只是多等一轮。
   - 速度：第一题中位 23 秒，整组中位 77 秒；最慢两套（189 秒、166 秒）都是 sub2api 某次审题卡了 2–3 分钟（其余审题中位 6–7 秒），超过 `wait_budget_seconds` 后题库补位。
   - token：审题一题一次，89 次输入共 48.7 万，是出题输入（11.7 万）的 4 倍；一次约 5.5k，而 `features.yaml` 的默认估计是 1.2k。
3. **提示词现状**：`exercise_generate.md` 用一段话讲每种题型，没有例子，没有写哪类错误适合哪种题型；出题模型要先给自己的题评难度再写题。`exercise_critic.md` 带学习者水平，结尾“Be strict”，所以 critic 会因为“对这个学习者太难”拒掉本该出的 B2 题。
4. 对话里的私教也会自己出小问题（举例让学习者判断、口头检查理解），用的是同一套出题经验，但现在只在出题管线的提示词里。

## 决定

### 1. 通用 skills 机制（`backend/app/skills/`）
- 格式沿用 Agent Skills：每个 skill 一个目录，`SKILL.md` 带 frontmatter（`name`、`description`）和总则，细节放 `references/*.md`，按需再读。
- **只加载仓库里的内置 skill、只按名字找**：不接受路径，不读用户或租户上传的内容；名字不在清单里、带路径分隔符的一律拒绝。skill 内容和提示词一样进 git、按内容哈希算版本（ADR 0033）。
- 接口：`skill_index()`（名字和描述，给系统提示列清单）、`load_skill(name)`（`SKILL.md` 正文）、`load_reference(name, part)`（某一份细节）。frontmatter 缺字段、`references` 里没有的部分报错，启动时就能发现。
- 为什么做成 skill，不直接加提示词文件：同一份内容有两种用法。出题管线由代码按这一组用到的题型直接拼进去；对话里由私教需要时自己读，平时只占一行描述。以后别的经验（比如讲解、批改）也按这个格式加。

### 2. 出题 skill `exercise-writing`
- `SKILL.md` 写总则：先把完整句子写出来、自查“还有没有别的填法 / 别的错处”，再定答案；**指令和提示不能把要考的形式直接给出来**（例如不能写“把 always 放在 are 后面”“用 bored 改写”），学习者得靠这个语法点自己得出答案。
- `references/<题型>.md`：每种题型的技巧、一个好例子和一个坏例子、常见坑。坏例子用这次真实被拒的题改写，不含个人信息。写明哪类错误配哪种题型：缺词的错（漏助动词、漏冠词）不出 find_fix，改出 cloze 或 transform；cloze 用 `hint` 锁住肯定 / 否定和词数。
- 出题管线按这一组用到的题型拼入对应的 references，替换 `exercise_generate.md` 里的各题型说明；再附同一语法点的 1–2 道题库题（`items.yaml`，全站通用、不含个人信息）作示范，没有就不附。

### 3. 输出 schema 加自查字段
- choice4 / cloze 在答案字段之前加 `other_fillings`：除了正确答案，这个空还能填什么、凭什么排除。find_fix 加 `error_kind`，只允许“形式错”或“用词错”，其他值逐题退回重写（ADR 0021 Q33b 的格式校验）。
- 字段顺序放在答案前面，让模型先想再写答案。这些字段只用于出题，不给学习者看，也不给 critic 看（critic 照旧不看答案，独立作答）。

### 4. 修订 Q33a：难度不再按分歧拒题
- `drafts.judge` 不再比较两边的评档，也不再因为分差拒题；分差照样算出来，写进 `exercises.critic`，留作评估。题目难度仍取 critic 的评档（原来就是这样）。
- 出题模型不再自评 4 个维度（schema 去掉 `ratings`），只拿到一句文字目标（比如“比较容易：提示明确、句子简单”）。目标被限制到 rubric 下限时，提示词写明“这已经是这个语法点能出的最简单”，不再让它去凑一个达不到的数字。
- `practice.critic_max_gap` 从 `rules.yaml` 去掉，规则升版本（预生成的组按 Q33e 重出）。
- 落地（任务 100.6）：文字目标由代码按 rubric 挑出各维度离目标最近的一组档位，写成“各维度要什么样”，`exercises.critic` 记 `target_difficulty` 和 `difficulty_gap`（critic 的难度减目标），不再记出题模型的评档。critic 评估集原来的 3 条 `misrated` 用例（难度标反、期望拒题）改成期望通过的好题，新指标 `rated_from_item` 检查 critic 的评档落在目标的哪一侧，即它是看题评的、不是照着目标评的；回放基线随之更新（`good-choice4-since` 原来只因分歧被拒，现在通过）。
- **不留“明显太难才拒”的兜底**（用户 2026-10-17 确认）：critic 的评档已经决定题目难度，Elo 按这个难度记账；拿“太难”拒题会把 critic 按学习者水平拒 B2 题的问题带回来。

### 5. critic 改成清单、只审题
- 去掉学习者水平和“Be strict”。critic 只回答题目本身的问题，逐项判：
  1. 答案对不对（closed 题看它自己的答案和标准答案是否一致，代码比对，不变）；
  2. 看完整句，是不是只有一个答案；
  3. 考没考到这个点，其中单列一项：指令或提示有没有把要考的形式给出来；
  4. 英语自不自然、有没有事实错误。
- 仍然按 rubric 评难度（用于定难度，不用于拒题）。审题输入 token 是出题的 4 倍，精简提示词时一并查清一次 5.5k 的来源。
- 落地（任务 100.7a、100.7）：5.5k 的来源不在提示词，而是 langchain-openai 见到 `gpt-6*` 模型且请求带 tools 时自动改走 Responses API，sub2api 那条通道同一份审题请求多算约 4.3k 输入、缓存为 0；`openai_compatible` 连接现在默认走 Chat Completions（连接参数 `use_responses_api: true` 可打开）。审题结果按清单分成 `answer_ok`、`one_answer`、`tests_kc`、`form_hidden`、`content_ok` 五项，每项失败各有拒因；`critic_messages` 不再收学习者信息，消息里只有 rubric 和题目。评估回放在 pytest 里跑（CI 也跑），critic 评估集在 100.7 就用 sub2api 重录了：`good-translate-going-to` 的指令给出了要考的形式，改成坏题（新拒因 `gives_away`）；3 条好题按 skill 的标准其实不止一个答案（无 hint 的介词、过去式也能填的过去完成时、把 a 改成 the 也通的 find_fix），换成只有一个答案的写法。坏题加了 2 条 `gives_away`（transform 的开头带出被动、cloze 的 hint 就是答案），连跑两遍坏题 26/26、好题 20/20。

### 6. 对话里的 `load_skill`
- 系统提示在稳定前缀（ADR 0053 §1，利于缓存）里列出 skill 的名字和描述。私教要自己出题、出检查问题时调 `load_skill(name)`，读 `SKILL.md`；工具结果里列出可再读的部分。
- 按 ADR 0013：参数只有 skill 名字，不带身份；只读、没有副作用，重复调用结果相同；名字不对作为工具结果返回，不中断这一轮。
- **单独计数**：每轮每个 skill 最多读一次，不占 `MAX_TOOL_ROUNDS`（读 skill 不该挤掉出卡的机会）；超过的调用直接返回“这一轮已读过”。
- **只留在当轮**：读到的内容只在这一轮的上下文里，之后的轮次在历史里换成一行“已读过 exercise-writing”，不让每轮输入一直变大。
- **课程对话由代码直接拼入**理解检查要用的那部分，不等模型自己想起来读：课程对话一定会出检查，确定要用的内容没必要多花一次工具往返。
- 活动记录记一行 `load_skill`（摘要：skill 名字），学习者看到“读了出题技能”。

## 取舍
- **不提高题库补位率**：用户明确要求先把生成做好；题库题少、没有讲解，补位多了练习就变成固定题。
- **去掉难度分歧会不会放过难度离谱的题**：会有。但分歧拒题的样本里没有一条是“题目真的太难”，都是出题模型在下限报不准；难度以 critic 的评档为准，学习者答题后 Elo 照样按它记账。分差存进 `exercises.critic`，评估时能看出 critic 和目标偏多远。
- **`load_skill` 多一次工具往返**：读 skill 的那一轮慢几秒、多几千 token。只在私教自己出题时才读，结果不留到下一轮；任务 100.9 统计触发率、误触发率和多出的 token、耗时，不划算再收紧。
- **只做内置 skill**：通用的 skill 加载（任意路径、用户上传）有路径穿越和提示词注入的风险，这个项目用不上。
- **这次不处理 sub2api 单次调用卡 2–3 分钟**：那是厂商侧的停顿，`wait_budget_seconds` 已经兜住（题库补位）；单次调用超时另议。
- 提示词和 schema 改了，评估集的录制回放要重录（ADR 0033），在任务 100.9 用 sub2api 重录，并把真实拒题的改写样例加进 critic 的评估集。
