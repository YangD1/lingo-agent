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
- 发消息的接口是 `POST /conversations/{id}/messages`，响应格式为 `text/event-stream`，用 FastAPI 0.141 内置的 `fastapi.sse.EventSourceResponse` 生成（支持 POST，空闲时自动发 keepalive 注释），不再引入 sse-starlette。
- 事件类型：
  - `token {text}`：一段增量文本
  - `done {message_id, usage}`：回复结束
  - `error {code, message}`：出错
- 后端用 `graph.astream(stream_mode="messages")` 拿 token，只转发 tutor 节点的 AI 消息。
- 开流前能判定的错误用 HTTP 状态码返回，body 为 `{"detail": {"code", "message"}}`：会话不存在或不属于当前用户返回 404；租户没配聊天模型返回 409 `no_llm_configured`；同一会话已有回复在生成时返回 409 `conversation_busy`。开流之后出的错只能用 `error` 事件表达（`llm_unavailable`，文案固定，不转发厂商错误文本）。
- **实现细节**（P0 任务 9）：
  - FastAPI 内置 SSE 在执行接口体**之前**就发出 200 响应头（接口体在一个 producer task 里跑），所以上面的 404 和 409 检查都放在 yield 依赖 `start_turn` 里。会话锁在它的 finally 里释放；yield 依赖挂在 request 级的 exit stack 上，流结束或客户端断开之后才退出。
  - 客户端断开时，FastAPI 通过 anyio cancel scope 取消 producer。这种取消是电平触发的，会连 LangGraph 自己的清理 await 一起打断，使节点 task 被遗弃、上游继续生成（冒烟时实测跑满了整段回复）。所以 `stream_reply` 把图放在独立的 asyncio task 里跑，断开时显式 cancel，并在 shield 的 scope 里等它清理完。
  - 断开后 LangGraph 只保存已完成的节点：用户消息保留，半截回复不保留。
- **经 Next rewrites 代理时的缓冲问题**（任务 10.1 验证，Next 16.3.6）：`next dev` 和 `next start` 都通过内置的 `compression` 中间件对 `text/event-stream` 做 gzip，**整段回复被缓冲到结束才一次发出**。浏览器总会带 `Accept-Encoding: gzip`，所以这个问题必然出现。`compression` 遇到 `Cache-Control: no-transform` 会跳过压缩（RFC 9111 也规定中间层不得改写这类响应），因此后端在 `start_turn` 里追加 `Cache-Control: no-transform`，最终响应里是两行 Cache-Control：FastAPI 自带的 `no-cache` 和新加的这一行。加上之后 dev 和 start 都能逐块到达，并且整站其他响应的压缩不受影响，所以**不需要走“浏览器直连后端 + CORS”的备选方案**。同时验证了：客户端 abort 会经过代理传到后端，后端的 producer 会收到取消，“停止生成”在代理下同样有效。
- 浏览器原生的 `EventSource` 只能发 GET，也不能带自定义请求体。所以前端改用 `fetch` 发 POST，拿到 `response.body` 后用 `eventsource-parser` 解析，用 `AbortController` 实现“停止生成”。

## 取舍
- **cookie 与 localStorage + Bearer 的比较**：cookie 方案更安全，代价是必须经过同源代理。Next rewrites 代理 SSE 时的缓冲问题已在任务 10.1 实测确认，并用 `no-transform` 解决（见上文）；备选方案（只让 SSE 接口由浏览器直连后端、走带凭据的 CORS）不再需要。
- **自定义 SSE 与 Vercel AI SDK 协议的比较**：AI SDK 的 `useChat` 能省掉前端代码，但后端必须按它的协议格式输出，而且要跟着它的版本升级。自定义事件协议很小，前后端各写大约 50 行就够，也方便在文档里讲清楚原理。以后如果要支持工具调用过程、引用来源这类富事件，只需在这个协议里加新的事件类型。
