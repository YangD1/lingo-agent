# 0047 · 路由的思考强度；只有调用参数的任务也能设路由

- **状态**：已采纳（2026-10-16，任务 89.2；按推荐确认）
- **日期**：2026-10-16
- **影响**：补充 ADR 0002、0004。`CallParams` 新增 `reasoning`；`SectionSpec.all_routes` 把只在 `task_params` 里出现的任务也算作可设路由的任务；设置页的文字模型路由加“思考强度”，新增“出题模型”“审题模型”两张路由卡片。无迁移。

## 背景
- 学习者觉得助手回复“不流式”。实测（任务 89.1）：后端、Next 代理、浏览器都在逐块输出。实际原因是聊天走推理模型（经 sub2api 中转的 `gpt-6-sol`），先思考几秒才出第一个字，之后很快出完，看起来就像“等半天，一次全出来”。
- 推理模型可以调低思考强度，但各家的参数不同：OpenAI 系用 `reasoning_effort`（`gpt-6-sol` 支持 none / low / medium / high / xhigh / max）；百炼和硅基流动只认 `enable_thinking`，会忽略 `reasoning_effort`（2026-10-16 实测 qwen-plus）。租户的参数白名单 `CallParams` 两个都不允许，设置页也没有地方改。
- 出题（`exercise_generate`）和审题（`exercise_critic`）要等整组题出完才显示，适合换成更快、不推理的模型，但设置页没有这两个任务。顺带发现：`reflect` 和 `exercise_generate` 在 YAML 里只有 `task_params`、没有 `routes`，后端不认它们是可设路由的任务。所以设置页的“后台整理模型”卡片一直读不到路由，保存也会返回 422。

## 决定

### 1. 一个跨厂商的参数：`reasoning`
- `CallParams.reasoning`：`off` / `low` / `medium` / `high`，不设表示用厂商默认值。不直接开放 `reasoning_effort`、`extra_body`：`extra_body` 能带任意字段，白名单就失去意义了。
- 建模型时按连接翻译成厂商自己的参数（`providers/llm.py` `reasoning_kwargs`）：
  - 连接地址是百炼（`*.aliyuncs.com`）或硅基流动：发 `enable_thinking`。`off` 发 false，其他档都发 true（这两家只有开和关）；
  - 其他 `openai` / `openai_compatible` 连接：发 `reasoning_effort`，`off` 对应 `none`；
  - `anthropic`、`deepseek` 类型不发：它们不会自己开思考，各家开启的方式也不同，这次不做。
- 只能设在文字模型（`llm`）的路由上，其他节的路由会拒绝。也可以设在连接上，那样对这个连接的所有文字调用都生效。`reasoning` 不会原样传给 SDK，`sdk_params` 会把它去掉。
- 模型不支持这一档时，调用会失败，然后走回退链；设置页的说明里提示改回“默认”。
- 代码不替租户改默认值：哪个模型适合关思考，取决于租户配了什么模型（Q：设置页手动选）。

### 2. 只有 `task_params` 的任务也能设路由
- `SectionSpec.all_routes()` = 默认路由 + `task_params` 里的任务（都先用默认路由）+ `routes`。这样 `reflect`、`exercise_generate`、`article_rewrite` 等任务都会出现在 `/tenant/routes` 里，也能保存自己的路由。

### 3. 设置页
- 文字模型的路由卡片（对话、后台整理、看图、出题、审题）在模型列表下面有“思考强度”下拉框（默认 / 关 / 低 / 中 / 高），改了立即保存，和停用某个模型的开关一样。
- 保存路由时保留它原有的参数（比如温度、思考强度、朗读音色），只替换这次改的那一项。以前保存时除了音色，其他参数都会被清掉。
- 新增“出题模型”“审题模型”两张卡片。

## 实测（2026-10-16，sub2api `gpt-6-sol`，app 真实提示，每档 3 个问题的首字时间）
- 默认：7.9 / 2.0 / 2.9 秒；低：3.0 / 2.8 / 2.0 秒；关：2.6 / 2.8 / 2.0 秒。约 2 秒是处理约 7000 token 输入的固定开销。

## 后果
- 学习者可以按自己配的模型，在设置页调低聊天的思考强度来缩短等待；出题和审题可以单独换模型、关思考。
- 以后新增厂商时，如果它的思考开关是另一种参数，就在 `reasoning_kwargs` 里加一个分支。
