# 0008 · 用户消息的多模态输入：图片、语音、文档

- **状态**：已采纳
- **日期**：2026-09-29（同日修订：支持扫描版 PDF，处理改为后台任务）
- **影响**：新增 `attachments` 表和附件接口；provider 层新增 `llm.vision` 任务和 `asr` 一节（ADR 0002 的 `speech.asr` 改为走租户连接，与 ADR 0004 “语音相关的 key 也由租户配置”一致）；PLAN 的 P3 中 “dev 本地 faster-whisper” 改为 “本地 OpenAI 兼容语音服务（speaches）”。其他 ADR 不变。

## 背景
P0 的聊天只能收纯文本。用户希望消息里可以带：
- **图片**：拍照的练习题、课本页、英文截图，或者“这个东西英语怎么说”；
- **语音**：直接说一段英语；
- **文档**：PDF、Word、txt，后续可能要对这些内容做 RAG。

有几个约束直接影响设计：
1. **图片不能内联在对话历史里**。Postgres checkpointer 每一步都会把整个 `messages` 通道完整序列化成一条新的 blob（`langgraph/checkpoint/postgres/base.py` 的 `_dump_blobs`，按 channel + version 写入，`ON CONFLICT DO NOTHING`）。一张 500KB 的 base64 图片会随着之后的每一轮被再存一遍。
2. **无法自动判断模型能不能看图**。各家 `/models` 接口不返回能力信息（ADR 0007 只能按名字粗分类）。同一个厂商下不同模型的能力也不同（比如 DeepSeek 官方 API 现在接受 `image_url`），中转站的情况就更难说了。
3. **服务器配置很低**：不能在后端跑 whisper，也不装 ffmpeg 这类重依赖。
4. LangChain 已经有统一的多模态消息块：`{"type": "image", "base64": ..., "mime_type": ...}`（`langchain_core/messages/content.py` 的 `ImageContentBlock`）。`langchain-openai` 和 `langchain-anthropic` 负责转换成各家格式，业务代码不用管厂商差异。

## 决定

### 1. 统一模型：每个附件都有一份“派生文本”
附件分三类，每类在上传时都会生成一份**纯文本表示**，保存在附件上：

| 类型 | 格式 | 派生文本从哪来 | 用户可见和可改 |
|---|---|---|---|
| `image` | JPEG / PNG / WebP / GIF（只取第一帧）；不收 SVG | `vision` 路由的模型读图，输出结构化的 `ImageReading{text_in_image, description}`（Pydantic） | 可以查看、修正识别结果 |
| `audio` | webm / ogg / mp4(m4a) / mp3 / wav | `asr` 路由的模型转写 | 转写结果先回填到输入框，用户确认或修改后再发送 |
| `document` | PDF（包括扫描版）/ DOCX / TXT / MD | 有文本层的页面直接抽取文字（pypdfium2、python-docx）；**没有文本层的页面（扫描版）渲染成图片，交给 `vision` 路由的模型逐页识别** | 可以查看 |

派生文本是后续所有功能共用的接口：对话历史、长期记忆抽取（P1）、错题抽取（P1/P2）、文档 RAG（§8）都只读它，不需要各自再处理原始文件。

### 2. 存储：PostgreSQL `attachments` 表（bytea）
- 字段：`id`、`tenant_id`、`user_id`、`conversation_id`（级联删除）、`message_id`（发送时才填，可为空）、`kind`、`mime_type`、`filename`、`size_bytes`、`sha256`、`data`（bytea，查询时默认不加载）、`status`（`processing` / `ready` / `failed`）、`text`（派生文本）、`meta`（JSONB：图片的宽高、`ImageReading` 的结构化结果、音频时长、文档页数、是否截断等）、`error`、`created_at`。
- **大小限制**：图片 5MB（前端会先压缩到长边 1600px 的 WebP 或 JPEG，一般 <500KB）；音频 10MB 且不超过 3 分钟；文档 20MB，PDF 最多 50 页，抽取的文字最多 200k 字符。单条消息最多 5 个附件，其中图片最多 4 张。
- **生命周期**：删除会话时附件随之删除（外键级联）。上传后一直没发送的附件，超过 24 小时就清掉：每次上传时顺手清理，不引入定时任务。附件属于用户数据，满足“用户可以删除自己的数据”这一要求。
- 这样不增加新服务，备份跟着数据库走。如果以后附件量大到值得拆出去，把 `data` 列换成对象存储的 key 就行，接口不变。

### 3. 上传与处理流程
1. 用户选择、粘贴或拖入文件，或者录一段音。前端先压缩图片（canvas 重新编码，顺带去掉 EXIF 里的 GPS 等信息）。如果当前还没有会话，就先建一个（和现在第一次发消息时的做法一样）。
2. `POST /conversations/{id}/attachments`（multipart）。后端**同步**完成校验、入库后立即返回 `processing`；派生文本由**进程内的后台 asyncio 任务**生成（不引入 Celery 或 Redis），前端轮询 `GET /attachments/{id}` 查看状态和进度（扫描版 PDF 显示“第 x / y 页”）。
   - 后台任务：每个进程共用一个信号量，限制同时调用看图模型的次数（初定 4），扫描版 PDF 的多个页面也受这个限制。任务会用到租户的 provider 上下文，这个上下文在任务开始时重新加载，不从请求里带过去。
   - 进程重启时，还在 `processing` 的附件会被标为 `failed`（原因是“处理被中断”），用户点重试即可。
   - **校验时不信任客户端声明的类型**：按文件头的魔数判断真实类型。图片用 Pillow 解码并重新编码：限制最大像素数、先按 EXIF 方向转正再去掉 EXIF、长边超过 1600px 时缩小，统一输出 JPEG（各家看图接口都支持；WebP 不是每个 OpenAI 兼容中转都支持）。JPEG 用 `draft()` 按缩小后的尺寸解码，4800 万像素的照片处理时内存峰值约 20MB（完整解码约 164MB）。bytea 列设为 `STORAGE EXTERNAL`，因为内容已经压缩过，不必让 PostgreSQL 再压缩一次。音频只识别容器格式，不解码也不转码。文档限制页数和字符数，解析超时就失败。
   - **扫描版 PDF 的判断按页进行**：某一页抽出的文字少于 20 个非空白字符，就当作扫描页，用 pypdfium2 按 150 DPI 渲染（长边限制在 1600px），交给 `vision` 识别。所以文字页和扫描页混排的 PDF 也能处理。渲染出的页面图片只在处理时用，不保存。
   - 需要的路由解析不出来时，返回 409：图片是 `no_vision_model`，语音是 `no_asr_model`。扫描版 PDF 要到抽取时才能发现，这时附件标为 `failed`，原因同样是 `no_vision_model`。前端引导用户去设置页。
   - 调用模型失败时，附件标为 `failed` 并带上原因，用户可以重试或移除。
3. `PATCH /attachments/{id}`：修正派生文本（图片识别结果、语音转写）。`POST /attachments/{id}/retry`：失败后重试。
   - **修改和删除都只允许在发送前进行**，发送后返回 409 `attachment_sent`：已发送的附件是历史的一部分，改了等于偷偷改写导师已经回答过的内容。
   - 错误码：`unsupported_file_type`（415）、`attachment_too_large`（413）、`invalid_image`（422）、`attachment_limit`（409，同一会话里未发送的附件最多 10 个）、`attachment_not_ready` / `attachment_not_failed` / `attachment_sent`（409）、`attachment_not_found`（404）。处理失败时 `error` 字段存错误码（`no_vision_model`、`processing_failed`、`processing_interrupted` 等），给人看的英文原因放在 `meta.error_message`。
   - 音频时长上限（3 分钟）只在前端录音时限制；后端只限制大小，因为判断时长要解码音频。
4. `GET /attachments/{id}/content`：必须登录，只能访问自己的附件，否则一律 404。`Content-Type` 取后端校验出的类型，带 `X-Content-Type-Options: nosniff`；图片和音频用 `inline`，文档用 `attachment` 下载。`DELETE /attachments/{id}` 只能删还没发送的附件。
5. 发消息：`MessageIn` 增加 `attachment_ids`。只接受属于同一会话、状态为 `ready`、还没发送过的附件。另外，语音消息的正文可以为空，这时直接用转写结果作为正文。

### 4. 附件怎么进入对话：原图只随当前轮发送，之后的轮次只带派生文本（“两者结合”）
- **checkpoint 里只存文本**：`HumanMessage` 的 content 仍是用户输入的文字，id 由后端生成，附件通过 `attachments.message_id` 关联到这条消息。这样 checkpoint 保持小体积，也不绑定任何厂商的格式。
- tutor 节点组装发给模型的消息时，通过运行时 context 里的附件读取器，按消息 id 查出附件：
  - **历史轮次**：在用户的文字后面附上各附件的派生文本（带标注，比如“[图片 1 · 识别内容] …”“[文档 notes.pdf] …”）；
  - **当前轮**：除了派生文本，**图片还附上原图**（标准 `image` 块），这一轮的回复**改由 `vision` 路由的模型生成**（它能看图）；不带图片的轮次照常用 `chat` 路由。
- **语音消息**：转写结果就是这条消息的正文；音频只保存下来，用于回放，以后也可以用来做发音评测（P3）。不把音频发给对话模型。
- **文档**：派生文本整段放进上下文，但每轮有总字数上限（初定 20k 字符），超过就截断，并告诉模型和用户“只读取了前 N 字”。按需检索留给 RAG（§8）。

### 5. 路由与能力：新增 `vision` 和 `asr` 两个任务，都要显式配置
- `llm.routes.vision`：负责读图（生成 `ImageReading`）和回复带图的那一轮。YAML 默认路由只写确认支持看图的模型。**ADR 0007 §3 的自动兜底不适用于 `vision`**：连接的默认模型不一定能看图，猜错了模型会编造看不到的内容，这对学英语的人危害很大。
- 新增 `asr` 一节（和 `embedding` 一样是单独的一节，也不走自动兜底）。provider 层新增 `get_asr(ctx)`，调用 OpenAI 兼容的 `POST {base_url}/audio/transcriptions`（multipart），同样走 SSRF 防护客户端。支持这个接口的有 OpenAI、Groq（`whisper-large-v3-turbo`，接受 webm）、SiliconFlow，以及本地的 speaches（faster-whisper）。
- **dev 环境的本地 ASR** 改为 compose profile `asr` 里的 speaches 容器，在设置页里把它加成一个连接。后端进程里不跑 whisper，所以 prod 和 dev 走同一条代码路径，唯一的区别是连接的地址。
- 设置页的路由编辑（11A.5）从只能编辑 `chat` 扩展到 `chat`、`vision`、`asr` 三个任务。
- **实现补充**：
  - YAML 里的 `vision` 路由只写 Claude 和 GPT。`asr` 默认用 `groq:whisper-large-v3-turbo`，备用 `openai:gpt-transcribe`：OpenAI 现在推荐 `gpt-transcribe`，`whisper-1` 和 `gpt-4o(-mini)-transcribe` 已宣布在 2027-02 下线。
  - 转写请求一律用 `response_format=json`，因为 `verbose_json` 只有 whisper 系支持。
  - 新增预设 `groq`，以及只在 dev 使用的 `speaches`。
  - 补充（2026-09-29，用户实测）：Groq 按地区屏蔽大陆 IP（直连 403），OpenAI 也不支持大陆，而后端调用模型时有意不走代理（防 SSRF），部署在大陆的服务器两个都用不了。新增预设 `siliconflow`（`https://api.siliconflow.cn/v1`，`FunAudioLLM/SenseVoiceSmall`，大陆可直连，兼容 `/audio/transcriptions`），asr 默认顺序改为 `groq → siliconflow → openai`。
  - 结构化输出（`ImageReading`）：openai_compatible 连接改用 `method="function_calling"`，因为 `ChatOpenAI` 默认的 `json_schema` 很多中转和非 OpenAI 模型不支持。连接类型通过模型的 `kind:<类型>` 标签传给 `get_structured_llm`。
- 用量：读图调用照常记入 `llm_usage`（task=`vision`）。ASR 也记一条，`task=asr`，token 为 0；新增可为空的列 `audio_seconds`，厂商返回了时长就填上。

### 6. 前端
- 输入框：附件按钮（选图片或文档）、粘贴图片、拖拽文件、按住或点击录音（`MediaRecorder`：Chrome 录出来是 webm/opus，Safari 是 mp4/aac，两种都直接上传）。
- 每个附件显示一张卡片：缩略图或文件名、状态（识别中 / 完成 / 失败 + 重试）、查看和修改识别结果、移除。有附件还在识别时不能发送。
- 消息气泡里显示附件：图片缩略图（点开看大图）、音频播放器 + 转写文字、文档卡片（可以下载）。

### 7. 安全与隐私
- 附件内容只能由附件所属用户访问。图片会重新编码、不接受 SVG，响应带 `nosniff`，所以用户上传的文件不会被浏览器当成页面或脚本执行。
- 去掉 EXIF：前端的 canvas 重新编码会去掉一次，后端用 Pillow 再去一次，防止客户端绕过。
- 限制 Pillow 的最大像素数和 PDF 的页数，防止解压炸弹。解析失败时只返回通用原因，不把内部异常原文返回给前端。
- 附件属于个人学习数据，和 `data/` 一样不能进仓库。E2E 测试用的样例文件由测试代码临时生成。

### 8. 为 RAG 预留（这次不实现）
这次只保证文档的派生文本完整入库（包括截断标记）。以后做 RAG 时新增 `attachment_chunks`（切分 + pgvector 向量，用现有的 `embedding` 路由），`§4` 里“整段放进上下文”的做法改为按问题检索相关片段。表结构和接口都不需要推倒重来。

## 取舍
- **进程内后台任务 + 轮询，不用任务队列**：扫描版 PDF 可能要调几十次看图模型，同步请求撑不住；而为此在低配服务器上引入 Celery 或 Redis 又不值得。代价是进程重启会中断正在处理的附件，需要用户重试；后端只跑一个 worker（任务 11.1），所以不存在多个进程抢同一个任务的问题。以后需要多 worker 时，再换成真正的任务队列，接口不用变。
- **扫描版 PDF 的费用和耗时**：每个扫描页都要调一次看图模型，费用由租户自己的 key 承担（用户确认可以接受），用量记在 `llm_usage` 里，可以查到。耗时靠并发上限和进度显示来缓解。
- **读图和回复都用 `vision` 路由**：会出现“带图那一轮换了一个模型回复”的情况。不这样做的话，就得猜 `chat` 路由的模型能不能看图，而猜错时模型会编造内容。用户如果希望所有轮次用同一个模型，可以把 `chat` 和 `vision` 设成同一个能看图的模型。
- **只有当前轮发原图**：之后的轮次如果问“再看一下图里第 3 题”，模型只能看到识别出的文字。识别结果（原文 + 描述）对练习题、课本这类图片已经足够；每轮都重发原图的成本会随对话长度线性增长。
- **PostgreSQL bytea 而不是文件卷或对象存储**：单个附件已经压缩并有上限，数据量可控；换来的是少一个服务、备份和删除逻辑都简单。
- **PDF 用 pypdfium2**（BSD-3 / Apache-2.0，wheel 约 3.6MB）：一个库同时负责抽取文字和渲染页面。不用 PyMuPDF，因为它是 AGPL 许可；也不再单独引入 pypdf。
- **不把 PDF 原文件直接发给模型**：Anthropic、OpenAI 等厂商支持直接收 PDF，但没法判断某个模型或中转站是否支持（和看图同样的问题），而且原文件每一轮都要重发。统一转成派生文本更可控。

## 补充（2026-09-29，11C）
连接的“测试”按用途测：模型名像语音转写模型（whisper / transcribe / SenseVoice / Paraformer），或者租户的语音转写路由用到了这个连接和模型，就发送一段内置的 0.5 秒静音 WAV 去调 `/audio/transcriptions`，而不是发一条聊天消息；请求里也可以用 `purpose` 显式指定。服务器返回 404（常见于只转发聊天接口的中转站）时返回 `error_code=asr_not_supported`，前端提示“这个连接不支持语音转写”。Anthropic 连接总是按聊天测。
