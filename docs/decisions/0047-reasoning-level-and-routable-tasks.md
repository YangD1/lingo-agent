# 0047 · 路由的思考强度；只有调用参数的任务也能设路由

- **状态**：已采纳（2026-10-16，任务 89.2；按推荐确认）
- **日期**：2026-10-16
- **影响**：补充 ADR 0002、0004。任务 91（2026-10-16）改写 §1、§3：档位按模型给、按模型存，厂商拒绝时去掉参数重试一次。`CallParams` 新增 `reasoning`；`SectionSpec.all_routes` 把只在 `task_params` 里出现的任务也算作可设路由的任务；设置页的文字模型路由加“思考强度”，新增“出题模型”“审题模型”两张路由卡片。无迁移。

## 背景
- 学习者觉得助手回复“不流式”。实测（任务 89.1）：后端、Next 代理、浏览器都在逐块输出。实际原因是聊天走推理模型（经 sub2api 中转的 `gpt-6-sol`），先思考几秒才出第一个字，之后很快出完，看起来就像“等半天，一次全出来”。
- 推理模型可以调低思考强度，但各家的参数不同：OpenAI 系用 `reasoning_effort`（`gpt-6-sol` 支持 none / low / medium / high / xhigh / max）；百炼和硅基流动只认 `enable_thinking`，会忽略 `reasoning_effort`（2026-10-16 实测 qwen-plus）。租户的参数白名单 `CallParams` 两个都不允许，设置页也没有地方改。
- 出题（`exercise_generate`）和审题（`exercise_critic`）要等整组题出完才显示，适合换成更快、不推理的模型，但设置页没有这两个任务。顺带发现：`reflect` 和 `exercise_generate` 在 YAML 里只有 `task_params`、没有 `routes`，后端不认它们是可设路由的任务。所以设置页的“后台整理模型”卡片一直读不到路由，保存也会返回 422。

## 决定

### 1. 一个跨厂商的参数：`reasoning`，按模型给档位（任务 91 改写）
- `CallParams.reasoning`：档位 `off` / `on` / `low` / `medium` / `high`，不设表示用厂商默认值。不直接开放 `reasoning_effort`、`extra_body`：`extra_body` 能带任意字段，白名单就失去意义了。
- **每个模型能用哪些档位、每档发什么参数**由 `providers/reasoning_catalog.py` `reasoning_spec(kind, base_url, model)` 根据连接类型、地址和模型 id 决定（和 `model_catalog` 一样按名字判断，尽力而为）：
  - OpenAI 系推理模型（o 系列、gpt-5 及以后）：发 `reasoning_effort`，档位按型号区分。gpt-5.1 及以后、`gpt-6-sol` 是关 / 低 / 中 / 高（关对应 `none`）；gpt-5、o 系列、`gpt-6.1-sol` 没有 `none`，只有低 / 中 / 高。`*-chat` 这类不推理的变体没有档位；
  - 百炼（`*.aliyuncs.com`）和硅基流动上的混合模型（Qwen3、qwen-plus / flash / turbo、DeepSeek V3.1+（V4 按 V3.1 推断，未实测）、GLM-4.5+）：发 `enable_thinking`，只有关 / 开；
  - 只会思考的模型（QwQ、`*-thinking`、DeepSeek R1）、不推理的模型、`anthropic` / `deepseek` 类型连接，以及**认不出的模型**：没有档位，什么都不发（Q91b）。
- 模型不支持的档位不发，所以不会因为这个参数报错。旧数据里开 / 关模型的低 / 中 / 高仍按“开”处理。
- **路由上按模型分别存**（Q91a）：`params.reasoning = {"连接:模型": 档位}`，保存时校验每个 ref 都在路由里，档位也在这个模型的可选档位里，否则返回 422。`/tenant/routes` 用 `reasoning_options` 返回每个模型的可选档位。连接上（和任务 91 之前保存在路由上的）仍然是单个值，对认得这个档位的模型生效。解析时取本模型的档位，没有就用连接的。只能设在文字模型（`llm`）的路由上。
- **兜底**（Q91c）：规则判断错时，厂商会返回 400，错误文字里会提到 reasoning / thinking。这时同一个请求去掉 `reasoning_effort` / `enable_thinking` 再发一次，并记一条 warning。这一步放在 HTTP 传输层（`WithoutReasoningRetry`，套在 SSRF 防护层外面），普通、流式、工具和结构化调用都能覆盖；只有确实发了思考参数的模型才套这一层。
- 代码不替租户改默认值：哪个模型适合关思考，取决于租户配了什么模型（Q：设置页手动选）。

### 2. 只有 `task_params` 的任务也能设路由
- `SectionSpec.all_routes()` = 默认路由 + `task_params` 里的任务（都先用默认路由）+ `routes`。这样 `reflect`、`exercise_generate`、`article_rewrite` 等任务都会出现在 `/tenant/routes` 里，也能保存自己的路由。

### 3. 设置页
- 文字模型的路由卡片（对话、后台整理、看图、出题、审题）里，每个模型那一行有自己的“思考强度”下拉框，只列出这个模型支持的档位（默认加上 `reasoning_options` 里的档位）。没有档位的模型不显示下拉框。改了立即保存，和停用某个模型的开关一样。
- 保存路由时保留它原有的参数（比如温度、思考强度、朗读音色），只替换这次改的那一项。以前保存时除了音色，其他参数都会被清掉。
- 新增“出题模型”“审题模型”两张卡片。

## 实测（2026-10-16，sub2api `gpt-6-sol`，app 真实提示，每档 3 个问题的首字时间）
- 默认：7.9 / 2.0 / 2.9 秒；低：3.0 / 2.8 / 2.0 秒；关：2.6 / 2.8 / 2.0 秒。约 2 秒是处理约 7000 token 输入的固定开销。

## 后果
- 学习者可以按自己配的模型，在设置页调低聊天的思考强度来缩短等待；出题和审题可以单独换模型、关思考。
- 以后新增厂商或型号时，如果它的思考开关是另一种参数或档位不同，就在 `reasoning_catalog.py` 的规则表里加一条。规则没有覆盖到的模型只会少一个可调项，不会报错。
