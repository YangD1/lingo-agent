# 0001 · 技术栈与部署约束

- **状态**：已采纳
- **日期**：2026-09-28

## 背景
项目要同时满足两点：个人日常能用，并且作为企业级 Agent 应用的参考实现。线上服务器配置很低（约 2C4G 或更低），需要尽量用免费 API。

## 决定
- 后端 FastAPI + LangChain/LangGraph，~~LangSmith 做可观测和评估~~（已被 ADR 0005 取代：自建用量表 + 可选 OpenTelemetry）；前端 Next.js。
- LLM 通过配置驱动的 provider 层接入（key 由租户配置，见 ADR 0004），默认支持 DeepSeek / Claude / OpenAI，可扩展到任意 OpenAI 兼容厂商；按任务路由模型。
- 存储：PostgreSQL + pgvector（业务数据、向量、LangGraph checkpointer/Store）+ Neo4j（语法知识图谱）+ Redis（可选）。
- 语音：开发环境用本地模型（faster-whisper / Kokoro），线上用 API（Groq/SiliconFlow ASR、edge-tts、Azure 发音评测免费档），配置切换且支持 fallback；实时对话用 Gemini Live / OpenAI Realtime，浏览器直连，后端只签发临时 token。
- 调度：APScheduler（不引入 Celery）。
- 记忆曲线：FSRS（开源），单词和语法知识点共用一个调度器。

## 取舍
- Neo4j 会多占内存（堆内存限制在 512MB）。如果线上资源不够，备选方案是 PG + Apache AGE。
- 免费 API 有额度限制，稳定性也没有保证，所以 provider 层必须支持降级链。
