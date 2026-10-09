# 0028 · 服务端朗读与发音评测的 provider：`tts`、`pronunciation` 两节和 Azure 语音连接

- **状态**：已采纳（2026-10-09，任务 52；P3 计划 D2、D5、D6 和 Q1–Q3 由用户确认，全部按推荐）
- **日期**：2026-10-09
- **影响**：落地 ADR 0018 §3（服务端朗读）和 §4（单词发音预生成）；provider 层新增 `tts`、`pronunciation` 两节和连接类型 `azure_speech`；新增表 `tts_audio`、`pronunciation_attempts`，`word_audio` 预生成任务；`features.yaml` 新增 `read_aloud`、`word_audio_prefetch`、`shadowing`；PLAN 的 `speech.tts` / `speech.pronunciation` 配置示例改为这里的两节。ADR 0001 里“线上用 edge-tts”早已被 ADR 0018 取代，这里不再变动。

## 背景
- ADR 0018 定了朗读三层：浏览器挑好声音（已落地）→ 单词发音预生成 → 可选服务端朗读，第 2、3 层当时只设计没实现，2026-10-01 移到 P3。
- P3 要做跟读和发音评测（PLAN 需求表“语音”一行），需要音素级打分；端到端实时语音模型不给音素分，所以发音评测一直是独立的 provider（PLAN P3 段）。
- 核实（2026-10-09，详见 `docs/plans/P3-voice.md` §2）：
  - Azure 语音 F0：发音评测和语音转写共用每月 5 小时、并发 1；神经语音朗读每月 50 万字符、每分钟 20 次请求。发音评测有音素 / 音节 / 词 / 全文粒度，韵律分只有 en-US；有参考文本（跟读）和无参考文本两种。
  - 兼容 OpenAI 的 `POST /audio/speech`：OpenAI（`gpt-4o-mini-tts`）、硅基流动，以及 speaches（MIT，已支持 Kokoro-82M 和 Piper 朗读，按需加载）。仓库的 `make asr-up` 起的就是 speaches。
  - 国内可用的发音评测：讯飞 ISE（每天 500 次免费）、腾讯智聆口语评测（无长期免费）。
  - 后端依赖里没有 ffmpeg / PyAV；Azure 短音频 REST 接口不收浏览器默认录的 webm。
- 未核实、开工时再核：Azure 在大陆能否访问、en-GB 发音评测支持哪些分数。

## 决定

### 1. 两个新节，和 `asr` 同样的规则（ADR 0008 §5）
- `tts` 和 `pronunciation` 各是单独的一节：走租户连接、按顺序 fallback，**只用显式配置的模型，不自动兜底到 `llm.default`**；YAML 里的默认路由只引用预设连接，租户没建的连接跳过。
- 每次实际调用记 `llm_usage`：`tts` 记字符数（新增可为空的列 `characters`），`pronunciation` 记 `audio_seconds`（ADR 0008 已有的列），token 为 0。
- 连接测试按用途测（同 ADR 0008 的语音转写）：朗读发一个短词，发音评测发内置的一小段 WAV。

### 2. 连接类型
- **`openai_compatible` / `openai`**：朗读走 `POST {base_url}/audio/speech`（`model`、`voice`、`input`、`speed`、`response_format=mp3`）。覆盖 OpenAI、硅基流动、本地 speaches / Kokoro。
- **新增 `azure_speech`**：填区域（如 `eastasia`）和 key，不填 base_url（由区域拼出地址，仍经 SSRF 防护客户端）；key 和其他连接一样加密存库（ADR 0004）。同一个连接同时可用于朗读（REST + SSML）和发音评测（短音频 REST，`Pronunciation-Assessment` 头）。不用 Azure SDK：REST 足够，少一个大依赖。
- 一个连接能做什么由类型决定：`azure_speech` 只能用在 `tts`、`pronunciation`，不能进 `llm`、`asr`；`pronunciation` 只接受 `azure_speech`（第一版）。

### 3. 朗读（ADR 0018 §3 落地）
- 路由里每个模型配声音：`voices: {en-US: ..., en-GB: ..., zh-CN: ...}`，没配的语言不由这个模型读。学习者的口音和语速（存在浏览器，ADR 0018 §2）随请求传给后端。
- 缓存表 `tts_audio`：租户、内容哈希（文本 + 语言 + 声音 + 语速 + 连接 + 模型）、格式、字节（`bytea`）、大小、最后使用时间。租户总量默认上限 200MB，超出按最久未用淘汰。缓存命中不记 `llm_usage`。
- 接口 `POST /speech/tts`：一次一句（≤ 1000 字符），返回音频；没配 `tts` 路由时返回 ~~404~~ 409 `no_tts_model`（见落地记录），前端据此不再请求。~~限流沿用现有机制。~~（项目还没有通用限流，见落地记录。）
- 前端：`speak()` 先请求后端，按句切分（沿用 ADR 0018 §1），逐句取音频顺序播放；没配、首字节超过 4 秒或出错时，整段退回浏览器朗读，本页记住“服务端不可用”，不再每句等待。
- **本地朗读（D6）**：dev 直接用现有 speaches 容器里的 Kokoro，在设置页把 speaches 连接加进 `tts` 路由即可，不新增容器。任务 53 实测内存后写进本 ADR 的落地记录和 README。原看板里的 MeloTTS 候选不做。线上仍然不在后端容器里跑模型（ADR 0018）。

### 4. 单词发音预生成（ADR 0018 §4 落地）
- 租户 owner / admin 在设置页对一本词书发起：先显示词数、预计字符数、按所配连接单价估算的费用（单价由租户填，不填就只显示字符数），确认后后台运行。美音、英音各一份；缓存进 `tts_audio`（预生成的条目不参与 LRU 淘汰，单独计量）。
- 进程内后台任务（同 `PracticeWorker` 的写法），分批、可断点续跑（按“词 + 口音”跳过已有的），进度存表，设置页显示进度、失败数，可暂停。
- 这是部署方手动发起、单独确认费用的操作，**不占 ADR 0025 的后台每日 token 上限**（Q7），但同样登记为 `timing: background`。
- 单词气泡、背单词页朗读单词时先查缓存，再按第 3 层、第 1 层退回。

### 5. 发音评测（D2）
- 第一个适配器 Azure：后端调短音频 REST 接口（≤ 30 秒），参考文本 = 跟读的句子，粒度到音素，`en-US` 时开韵律；返回准确度、流利度、完整度、（韵律）、逐词准确度和错误类型（漏读 / 多读 / 读错）、逐音素分。
- **音频格式**：跟读录音由浏览器用 Web Audio 直接编码成 16kHz 单声道 16 位 WAV（≤ 30 秒约 1MB）再上传；后端不做转码，不为此加 ffmpeg。录音时长上限 30 秒，静音拦截沿用 `use-recorder.ts` 的规则。
- **不把 Azure key 或授权 token 给浏览器**：录音经后端转发。这样 key 不出后端，用量和限额在后端掌握；代价是多一次上传，跟读音频很短，可以接受。
- **兜底**：没配 `pronunciation` 时，用 `asr` 转写，和参考文本做词级对齐（规范化后按编辑距离），标出漏读、读成别的词、多读，不给分数；界面写明“粗略结果，不是发音打分”。两者都没配时不显示跟读入口。
- 讯飞 ISE 作为第二个适配器，P3 之后有需要再做；接口按 provider 设计，不写死 Azure 的字段——评测结果统一成自己的结构（整体分、逐词、逐音素，取值 0–100），适配器负责换算。

### 6. 跟读数据与证据（Q1–Q3）
- 跟读的句子来源（Q1）：私教回复（按句选）、阅读文章段落、单词例句、口语小结里的“更地道的说法”。
- `pronunciation_attempts`：user、来源（chat / reading / vocab / speaking）、来源 id、参考文本、语言、提供方（`azure` / `asr_fallback`）、整体分 JSONB、逐词 / 音素 JSONB、时长、创建时间；随用户级联删除。
- **录音不保存**（Q3）：只存分数和转写。以后要“回听自己的录音”时再加，并让学习者可删。
- 证据（Q2）：只有真正的发音评测（不含转写兜底）计证据。整体分按 Elo 更新 `skill_estimates.speaking`（句子难度按长度和词频估，参数放 `rules.yaml`）；准确度低于阈值的词记一条单词发音证据，背单词页在这个词上标“你读不准”。**不给语法 KC 记证据**，也不影响语法掌握度。

### 7. 公示（ADR 0013、0014）
- `features.yaml`：`read_aloud`（`tts`，学习者点朗读时，按字符估算）、`word_audio_prefetch`（`tts`，background，按字符估算）、`shadowing`（`pronunciation`，兜底时是 `asr`，按音频秒数估算）。估算单位扩展为字符和秒（ADR 0014 已有 `audio_seconds`）。
- 朗读按钮的 `AiBadge` 只在租户配了 `tts` 路由时显示（浏览器朗读不调用模型，ADR 0018）。跟读入口挂 `AiBadge`。
- 都不是对话轮次里的工具调用，不写 `agent_activities`；`docs/agent-tools.md` 的“对话之外的调用”和后台任务各补一行。

## 取舍
- **发音评测走后端转发，而不是浏览器拿 Azure token 直连**：直连少一跳、能做边说边评，但 token 在 10 分钟内可以随便调 Azure 的任何语音接口，额度和用量就不归后端管了。跟读每句只有几秒，转发的成本很小。
- **浏览器编码 WAV，而不是后端转码**：后端加 ffmpeg 会让镜像和内存都变大（线上服务器配置低）；Web Audio 编码 16kHz WAV 只是几十行纯函数，可以单测。
- **先 Azure 后讯飞**：Azure 能力最全、和朗读共用一个连接、免费档够个人用；讯飞国内可用但协议私有，留到确实需要时再做。
- **转写对比兜底**：不准，但零额外配置就能用；界面明确说明是粗略结果，不计证据，避免误导。
- **朗读缓存存 Postgres `bytea`**：低配部署不想再加对象存储；单句 mp3 几十 KB，总量有上限，够用。以后量大再挪到文件系统或对象存储。

## 落地记录（任务 53，2026-10-09）
- **连接和路由**（53.1）：`azure_speech` 连接的 base_url 就是朗读地址 `https://<区域>.tts.speech.microsoft.com`（中国区 `.azure.cn`），改区域就是改 base_url，不另设“区域”字段；以后发音评测从它推出 `.stt.` 地址。Azure 连接属于 `SPEECH_ONLY_KINDS`：不能进 llm / asr 路由，不参与 ADR 0007 的自动兜底，从预设建连接时不设默认聊天模型；模型列表取 `cognitiveservices/voices/list` 里 en-US / en-GB / zh-CN 的声音。`llm_usage.characters`（迁移 `c8c4c75cd6e0`）。开发机不走代理直连 Azure 全球（eastasia、eastus）和中国区（chinaeast2）的朗读地址都能连上（返回 401，只差 key）。
- **声音**（53.2）：路由参数 `voices` 按“连接:模型”和语言覆盖（只能放在 tts 路由，因为连接参数会原样传给聊天 SDK）；没覆盖时用内置声音：Azure 的模型就是声音（多语言声音也读中文，但选英音时换成 `en-GB-SoniaNeural`），Kokoro `af_heart` / `bf_emma`，CosyVoice `<模型>:anna`，OpenAI 系 `coral`；都没有时这个模型跳过这种语言。合成不用厂商 SDK，直接经 SSRF 防护的 httpx 客户端；失败的请求也按字符记用量（请求已经到了厂商）。
- **缓存与接口**（53.3）：表 `tts_audio`（迁移 `87ef738892c1`），按路由顺序查缓存，备用模型录过的也直接用。**和 §3 不同**：没配朗读路由时返回 **409** `no_tts_model`（和语音转写、看图一致，原写 404）；路由里没有模型能读这种语言时 409 `no_tts_voice`，前端只把这种语言退回浏览器；`GET /speech/capabilities` 返回 `tts` 和 `tts_languages`。项目还没有通用限流（P4），这里只靠单句 1000 字符上限和缓存控制成本。缓存只存音频和哈希，不存原文，同租户共用，删除会话不会跟着删。
- **本地 Kokoro 实测**（53.4，开发机 32 核、容器不限 CPU，speaches 0.9.0-rc.3-cpu）：从 hf-mirror 下载 Kokoro 约 27 秒；加载后容器约 0.9 GB，两路并发峰值 1.48 GB（容器上限 2 GB）；一句 9.1 秒的英文单路约 2.0 秒、两路并发各约 2.6 秒。**speaches 的 Kokoro 不能读中文**：它用 espeak 做音素转换，espeak 没有 `zh`，接口返回 200 但没有音频，所以内置声音里去掉了 Kokoro 的中文。目标机器（4 vCPU、无显卡）没有实测，按 ADR 0018 的结论线上仍不跑本地模型。

## 落地记录（任务 54，2026-10-09）
- **前端**（54.1）：`lib/speech.ts` 每页问一次 `/speech/capabilities`（朗读按钮出现时）；**没问到之前全部由浏览器读、不等待**，保证浏览器朗读在点击里同步开始（Safari 要求）。文本按句切，服务端能读的语言逐句 `POST /speech/tts`、播当前句时预取下一句；共用一个 `Audio` 元素，开读时先在点击里播一小段静音解锁。`no_tts_voice` 只把那种语言退回浏览器；其他错误、4 秒没响应、空音频、播放被拒都把本页标为“服务端不可用”，从失败那句起由浏览器读，刷新后重试。
- **学习者开关**（Q54a，54.2）：朗读设置里“用服务端声音朗读”，存在当前浏览器、默认开；服务端读时本机声音只作备用。
- **设置页**（Q54b，54.3）：朗读路由可按“连接:模型”和语言（美音 / 英音 / 中文）指定 `voices`，`/tenant/routes` 对 tts 路由多返回 `default_voices` 作占位提示；Azure 连接按区域（和中国区勾选）生成 base_url，只用来朗读的连接不设默认模型；连接测试加“朗读”用途。
- **公示**（54.4）：朗读按钮只在服务端按学习者口音读英文时挂 `AiBadge read_aloud`；用量页有朗读记录时显示“朗读字符”。
- **缓存与隐私**（Q54c，54.5）：§3 原写“删除会话不会跟着删”，学习者删不掉自己的数据。改为 `tts_audio.user_id` 记第一次让它生成的学习者（迁移 `5ebd002ec068`，预生成的单词音频为空），`DELETE /speech/tts-cache` 删自己让生成的非固定音频，账号删除时级联；定时任务 `tts_cache_cleanup` 每天删 30 天没人播的非固定音频。同一句被别人再读过时，清除仍会删掉（对方下次重新合成）。
