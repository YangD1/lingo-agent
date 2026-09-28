# 0004 · 多租户模型凭据：租户自配 key、端点与路由

- **状态**：已采纳
- **日期**：2026-09-28
- **影响**：取代 ADR 0002 中“key 来自环境变量”和“启动时校验 key”两部分；0002 中的路由格式、降级语义和 embedding 不做降级链这几条继续有效。

## 背景
模型厂商的 API key 不应该写在部署配置（环境变量或 YAML）里，而应该由租户在应用内自己配置。已确认的需求：
- 租户粒度：每个用户注册时自动获得一个**个人租户**，数据模型预留组织和多成员，P0 不做邀请。
- **只使用租户自己的 key**，平台不提供兜底 key，也就不需要平台管理页。
- 租户能配置的范围尽可能大：Claude、OpenAI、DeepSeek，以及任意 OpenAI 兼容厂商，都可以改 **base_url**（中转代理、自建网关）、选模型、调整每个任务的降级链和调用参数。
- 在 P0 做完最小闭环。

## 决定

### 1. 各类配置放在哪里
| 内容 | 位置 | 谁来配 |
|---|---|---|
| 厂商**预设**（kind、官方 base_url、推荐模型）、任务列表、**默认路由** | `config/providers.*.yaml` | 部署方 |
| 租户的**连接**（厂商、base_url、key、额外参数） | DB 表 `provider_connections`，key 加密存储 | 租户 |
| 租户对某个任务的**路由覆盖**（模型链、temperature、timeout 等） | DB 表 `tenant_model_routes` | 租户 |
| 加密主密钥、JWT 密钥、可观测性配置（OTel，见 ADR 0005）、是否允许内网端点 | 环境变量 | 部署方 |

YAML 删除 `api_key_env` 字段，不再包含任何 key。

### 2. 路由怎么解析
对某个租户的某个任务：先看租户是否覆盖了这个任务的路由；没有覆盖就用 YAML 里该任务的默认路由；YAML 里也没有这个任务，就用 YAML 的 `default` 路由。

默认路由中的 `"<名字>:<模型>"`，按**同名的租户连接**去找。租户从预设创建连接时，连接名默认就是预设名，所以只要填上 key，默认路由就能直接用。租户还没建的连接会被跳过。整条链都没有可用模型时，接口返回错误码 `no_llm_configured`，前端据此引导用户去设置页。

### 3. key 加密
- 算法用 **AES-256-GCM**（`cryptography` 库）。每次加密生成随机 12 字节 nonce。**AAD 设为 `tenant_id:connection_id`**：把密文绑定到它所在的那一行，即使有人能直接改数据库，把 A 租户的密文复制到 B 租户的行里也解不开。
- 密文格式为 `v1:<key_id>:<nonce>:<ciphertext>`。主密钥放在环境变量 `CREDENTIALS_ENCRYPTION_KEYS`，形式是 `id1:base64key,id2:...`，第一个用于加密，全部都可用于解密。轮换主密钥的步骤：新增一个 key 放到最前面，执行 `make rotate-credentials` 把所有记录重新加密，然后删掉旧 key。
- 主密钥必须放在数据库之外，否则拿到数据库备份的人就能同时拿到密文和钥匙。缺少主密钥或格式错误时，服务拒绝启动（dev 和 prod 都是）。`make gen-key` 用来生成主密钥。
- API 永远不返回明文 key，只返回末 4 位，例如 `sk-…abcd`。日志里一律不打印 key。有测试确保模型对象的 repr、LangChain 序列化结果和 OTel span 属性里都不含 key。

### 4. SSRF 防护（租户可以填任意 base_url）
- **保存连接时**：只允许 `https`。解析域名后，如果任何一个 IP 落在 loopback、私网、link-local（含云元数据地址 169.254.169.254）、CGNAT、组播或保留地址段（IPv4 和 IPv6 都查），就拒绝保存。
- **发请求时**：保存时检查一次不够，因为 SDK 发请求时会重新解析 DNS，攻击者可以在两次解析之间改变解析结果（DNS rebinding）。所以连接时还要再查一次：自定义 `httpcore.AsyncNetworkBackend`，在 `connect_tcp` 里解析域名、检查 IP，然后**直接连接这个已经检查过的 IP**，TLS 的 SNI 和证书校验仍然用原域名。用这个 backend 构造 `httpx.AsyncClient`，然后：
  - ChatOpenAI、ChatDeepSeek：通过 `http_async_client` 参数传入。
  - ChatAnthropic：没有注入口，它的 client 是在私有 cached_property `_async_client` 里构造的。写一个小子类覆盖这个属性，并加回归测试。升级 langchain-anthropic 时如果这个测试失败，就要重新检查。
- 不跟随重定向。
- 部署方可以显式开启 `PROVIDER_ALLOW_PRIVATE_NETWORKS=true`（默认 false），用于自部署时连接本机 Ollama 这类场景。开启后允许 http 和内网地址。

### 5. provider 层的接口怎么变
- 每个请求开始时，从 DB 加载一个 `TenantProviderContext`，里面有租户的连接（key 已解密）、路由覆盖，以及版本号 `version`（取这些行的 `updated_at` 最大值和数量算出的指纹）。
- 调用方式改为 `get_llm(ctx, task)`、`get_structured_llm(ctx, task, schema)`、`get_chat_model(ctx, task)`、`get_embeddings(ctx, task)`。
- 构造好的模型实例放在进程内的**有界 LRU 缓存**里（大小可配置，并设 TTL），缓存键是 `(tenant_id, task, version)`。租户修改连接或路由后，version 变化，旧缓存条目自然失效。
- **LangGraph 里只在 `configurable` 中传 `tenant_id` 这类原始值**。ctx 通过 LangGraph 1.x 的运行时 context（`context_schema` 配合 `astream(context=...)`）传给节点。原因是 `configurable` 可能被写进 checkpoint 的元数据，如果把含明文 key 的 ctx 放进去，key 就会落盘。这一点在任务里要用测试验证。
- 启动时只检查 YAML 的结构；缺 key 不影响启动。

### 6. 租户可以用的 API（P0 里只有个人租户的 owner 能用）
- `GET /provider-presets`：列出预设厂商、默认 base_url、推荐模型、可配置的任务。
- `GET|POST /tenant/connections`、`PATCH|DELETE /tenant/connections/{id}`：管理连接。
- `POST /tenant/connections/{id}/test`：用一个极小的请求测试连接是否可用，结果写入 `last_verified_at` 和 `last_error`。
- `GET|PUT|DELETE /tenant/routes/{section}/{task}`：查看、覆盖、恢复默认路由。

## 取舍
- **只用租户 key**：平台不承担调用成本，也不需要平台管理员。代价是新用户必须先配 key 才能对话，所以前端要把首次引导做好。
- **开放 base_url**：灵活性最大，但带来 SSRF 风险，因此要做发请求时的 IP 检查。这部分代码是安全边界，必须有单测覆盖（私网、IPv6、DNS rebinding 模拟、重定向）。
- **ChatAnthropic 子类依赖私有实现**，升级时可能失效，靠回归测试兜底。
- **进程内缓存**：多个 worker 或多个副本各自缓存，靠 version 保证最终一致。修改配置后，最多在 TTL 时间内还可能用到旧实例，但只要 version 已经变了，就一定会重新构造。
- **语音相关的 key（P3：ASR / TTS / 发音评测 / realtime）也由租户自己配置**（用户已确认），沿用本 ADR 的连接、加密和 SSRF 方案。具体的预设和路由到 P3 再细化。
