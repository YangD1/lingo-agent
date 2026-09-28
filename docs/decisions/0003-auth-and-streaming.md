# 0003 · 鉴权令牌传输与对话流式协议

- **状态**：已采纳
- **日期**：2026-09-28

## 背景
P0 需要多用户登录，对话回复要逐 token 流式输出。有两件事要定：令牌放在哪里、怎么传给后端；流式输出用什么协议。

## 决定

### 1. 鉴权
- 用户用 email + 密码注册，密码用 `pwdlib[argon2]` 做哈希。签发的 JWT 用 HS256 算法，`sub` 存 user_id，`exp` 默认 7 天，可以用 `JWT_EXPIRE_MINUTES` 调整。
- 令牌放在 **httpOnly、SameSite=Lax 的 cookie** 里，生产环境再加上 `Secure`。前端 JS 读不到这个 cookie，即使页面被 XSS 注入了脚本，令牌也不会被偷走。
- 后端的 `get_current_user` 同时认两种来源：cookie 和 `Authorization: Bearer`。后者给 curl、测试和以后可能出现的非浏览器客户端用。
- 前端用 Next.js `rewrites` 把 `/api/*` 转发到后端。对浏览器来说这是同源请求，会自动带上 cookie，也不需要配置 CORS。
- 如果 `APP_ENV=prod`，而 `JWT_SECRET` 仍是默认值，服务拒绝启动。
- P0 不做 refresh token，也不做令牌黑名单：登出就是清掉 cookie。这两项放到 P4。
- 实现补充（任务 7）：
  - 非浏览器客户端通过 `POST /auth/token`（OAuth2 password 表单）拿 Bearer 令牌。这个接口不设 cookie；浏览器登录接口的响应体里也不返回令牌，这样页面上的 JS 在任何时候都拿不到令牌。
  - prod 下 `JWT_SECRET` 至少要 32 字节（RFC 7518 §3.2 要求 HS256 密钥至少 256 位；pyjwt 2.15 对更短的密钥只发警告，不会报错）。
  - 未知邮箱和密码错误返回同样的 401 响应，而且在邮箱不存在时也做一次 argon2 校验，保证两种情况耗时相同，没法通过响应时间判断某个邮箱有没有注册。
  - CSRF：cookie 设了 `SameSite=Lax`，浏览器在跨站的 POST、PATCH、DELETE 请求里不会带上它。需要登录态的写接口都只接受 JSON 请求体，跨站表单发不出这种请求，而用 JS 跨域发 JSON 会先触发 CORS 预检。有两个例外，风险都很低：
    - `/auth/token` 接受表单，但它不读 cookie、也不设 cookie，跨站页面又读不到响应，所以攻击者拿不到任何东西。
    - `/auth/logout` 没有请求体，理论上可以被跨站请求触发，最坏结果是用户被强制登出。

    所以 P0 不另外加 CSRF token；以后如果有跨站嵌入的需求再重新评估。

### 2. 流式协议：自定义 SSE 事件
- 发消息的接口是 `POST /conversations/{id}/messages`，响应格式为 `text/event-stream`，由 `sse-starlette` 生成。
- 事件类型：
  - `token {text}`：一段增量文本
  - `done {message_id, usage}`：回复结束
  - `error {code, message}`：出错
- 后端用 `graph.astream(stream_mode="messages")` 拿 token，只转发 tutor 节点的 AI 消息。
- 浏览器原生的 `EventSource` 只能发 GET，也不能带自定义请求体。所以前端改用 `fetch` 发 POST，拿到 `response.body` 后用 `eventsource-parser` 解析，用 `AbortController` 实现“停止生成”。

## 取舍
- **cookie 与 localStorage + Bearer 的比较**：cookie 方案更安全，代价是必须经过同源代理。已知的风险是 Next rewrites 在代理 SSE 时可能缓冲输出，开了压缩时更明显。任务 7/8 时要先验证这一点。如果真的会缓冲，就只让 SSE 这一个接口由浏览器直连后端，走带凭据的 CORS，其余接口不变。
- **自定义 SSE 与 Vercel AI SDK 协议的比较**：AI SDK 的 `useChat` 能省掉前端代码，但后端必须按它的协议格式输出，而且要跟着它的版本升级。自定义事件协议很小，前后端各写大约 50 行就够，也方便在文档里讲清楚原理。以后如果要支持工具调用过程、引用来源这类富事件，只需在这个协议里加新的事件类型。
