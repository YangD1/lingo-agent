# 0063 · 部署：宿主机 nginx、一次构建推两个仓库、发布镜像 + 锁死命令的 SSH 部署

- **状态**：已采纳（2026-10-23，任务 71；用户定：用宿主机 nginx 不用 Caddy；持续部署用 GitHub Actions → 私有镜像仓库 → ssh 触发，不用 Jenkins；Q71e1–Q71e5 按推荐；开源用户用 Docker Hub 公开镜像，私有仓库 + ssh 只自用）
- **日期**：2026-10-23
- **影响**：取代 README 原来“前面放 Caddy”的建议。新增 `deploy/`（`deploy-entry`、`deploy.sh`、`backup.sh`、`restore.sh`、`prune.sh`、`rehearse.sh`、`release.Dockerfile`、`systemd/`）、`.github/workflows/deploy.yml`、`docs/deploy.md`；compose 的镜像、前端绑定地址、Postgres 初始化目录可配（`BACKEND_IMAGE` / `FRONTEND_IMAGE` / `POSTGRES_IMAGE` / `IMAGE_TAG` / `FRONTEND_HOST_BIND` / `POSTGRES_INIT_DIR` / `RELEASE_IMAGE`）。不涉及模型调用和 agent 工具，`features.yaml` 和 `docs/agent-tools.md` 不变。

## 背景
目标服务器很小：2 核、约 1.6 GB 内存、无 swap，80 / 443 已经被宿主机 nginx 占着（跑着别的站点），装着一个常驻约 570 MB 的 Jenkins。服务器连不上 Docker Hub 和 GitHub（要经代理），在上面构建镜像会内存不够（本机 WSL 构建都出过 OOM）。

第一次部署（任务 71c）是手动的：本机构建 → `docker save | ssh docker load`，代码用 `git archive | ssh tar x`。能用，但每次要占着本机、步骤多、没有回滚。仓库是公开的，Actions 日志也公开。同时开源用户需要不用自己构建就能跑起来的镜像，而我们的私有仓库（阿里云容器镜像服务）在海外用不了。

## 决定

### 1. HTTPS：宿主机 nginx，不用 Caddy
服务器上已有 nginx 占着 80 / 443，Caddy 要么抢端口、要么套在 nginx 后面多一层，所以直接给 nginx 加一个站点，证书用 certbot。站点模板（去掉域名）放进 `docs/deploy.md`，并列出每项不配的后果，换别的代理时对照：

- `X-Forwarded-For` 用 `$remote_addr` **覆盖**（ADR 0035 的按 IP 限流读最右一项；Next 会原样转发浏览器带的头）；
- `FRONTEND_HOST_BIND=127.0.0.1`，前端只有代理能访问；
- WebSocket 升级头（实时通话）、`proxy_buffering off` 和 1 小时超时（SSE 流式回复）、`client_max_body_size 25m`（附件最大 20 MB）。

### 2. 一次构建，推两个仓库
`deploy.yml` 在 `v*` tag 上先调用 CI（`ci.yml` 加 `workflow_call`，测试不过不构建），然后后端、前端镜像**只构建一次**，按配置推到：

- **Docker Hub**（公开，给开源用户）：`<namespace>/lingo-agent-backend|frontend`，标签 `X.Y.Z`、`X.Y`、`latest`；带 `-` 的预发布只打自己的标签、不动 `latest`；只推 amd64。只在 `vX.Y.Z[-pre]` 形式的 tag 上推。
- **私有仓库**（自用服务器拉取）：标签 = 提交号 + git tag。另外推发布镜像（见 3），并按 digest 同步固定版本的 pgvector（服务器连不上 Docker Hub）。

每部分只在对应的 vars / secrets 存在时运行（check job 输出 `acr` / `dockerhub` / `deploy` 三个开关），fork 什么都不配就只跑 CI。私有仓库里已有这个提交的镜像时（重新部署、回滚）跳过 CI 和构建，直接部署。

### 3. 发布镜像 + 锁死命令的 SSH 密钥
服务器部署需要的文件（compose、`config/`、Postgres 初始化脚本、`deploy/`）不经 SSH 传，而是打成 `FROM scratch` 的**发布镜像** `RELEASE_IMAGE:<提交号>`，服务器自己从仓库拉。部署密钥在 `authorized_keys` 里是 `restrict,command="…/bin/deploy-entry"`，`deploy-entry` 只接受 `deploy <40 位提交号>`。

原因：最初的设计是把发布包经 stdin 交给 `deploy.sh`。但部署用户在 docker 组里（约等于 root），能传任意 compose 文件就能挂载宿主机根目录，密钥泄露 = 服务器沦陷。改成从仓库取之后，泄露的密钥最多只能重新部署 CI 构建过的提交。

部署用户是单独的 `deploy`（密码锁定、只用密钥），不复用管理员账号。

### 4. 发布目录、迁移判断和回滚规则
服务器布局 `LINGO_ROOT`（`/srv/lingo-agent`）：`releases/<提交号>/`（不可变，同一提交再部署复用目录，因为运行中的后端挂着它的 `config/`）、`current` 软链、`shared/.env`（唯一一份配置）、`shared/postgres-init`（固定目录，`POSTGRES_INIT_DIR`，切版本时不因挂载路径变了而重建 postgres）、`backups/`、`logs/`、`bin/deploy-entry`（每次成功部署后换成新版本里的那份）。compose 项目名固定为 `lingo-agent`，数据卷不随目录变化。

`deploy.sh` 的步骤：flock 防并发 → 拉镜像 → 比较新旧后端镜像的 `alembic heads` → 部署前备份 → `up -d --wait`（后端启动时迁移）→ 成功则切 `current`、清理（保留最新 5 个版本、30 天日志）。健康检查失败时（Q71e2）：

- **表结构没变**：自动换回上一个版本；
- **表结构变了**：**不自动回滚**（旧代码配新表结构不保证能跑），停在新版本、workflow 标红，并打印用部署前备份恢复的命令。不自动恢复备份，因为那会丢掉部署这几分钟里的写入，要人来判断。

LangGraph checkpointer 自带的迁移不在 `alembic heads` 里。它只加不删，旧代码能跑，所以不计入判断。

回滚 = 从旧 tag 手动运行 workflow（Q71e1：推 `v*` tag 部署 + 手动按钮），不单独做回滚命令。

备份（Q71e5）：每次部署前一份 + systemd 定时器每天一份，服务器上保留最近 14 份；异地备份以后再说。`.env` 里的加密主密钥要和备份分开另存，文档里单独强调。

### 5. 公开仓库的日志与 secrets 规则
- 服务器脚本往 stdout 只打印步骤和结果，命令输出和容器日志只写服务器上的 `logs/`；
- 服务器地址、端口、私钥、`known_hosts` 放 secrets，`StrictHostKeyChecking=yes`；`DEPLOY_USER` 用 variable（secret 的值会在日志里被替换成 `***`，“deploy” 设成 secret 会让日志里所有这个词消失）；
- 全部放在 `production` 环境，只允许 `v*` tag 使用；暂不开人工审批（单人维护，以后多人再开）；
- 第三方 action 按提交号固定；SSH 用系统自带的 `ssh`，不用第三方 ssh action；
- 镜像签名（cosign）留作以后加强。

### 6. 开源用户的文档
`docs/deploy.md` 主体写给开源用户：用 Docker Hub 镜像（或从源码 `make up`）跑在一个代码目录里，`umask 022`、生产配置、一次性容器导入词库（`docker compose run --rm`，不用 `exec`，导入例句要约 800 MB，不能和 768 MB 上限的运行中后端抢）、nginx 模板、备份恢复、升级和按 `alembic heads` 判断的手动回滚。持续部署作为可选一节，写成通用的（任何 OCI 仓库），私有仓库的变量名沿用 `ACR_*`。

## 取舍
- **不用 Jenkins / 服务器上常驻部署进程**：Jenkins 常驻约 570 MB，这台机器总共 1.6 GB；GitHub Actions 的 runner 免费，构建也不在服务器上做。代价是依赖 GitHub，GitHub 不可用时按文档手动构建推送，再在服务器上直接运行 `deploy-entry`。
- **不在服务器上构建**：内存不够，而且服务器拉不到构建依赖。
- **不每次推 main 就部署**：只在打 tag 时部署，版本和镜像标签一一对应，Docker Hub 上也只有版本号。
- **不用 Watchtower 一类自动拉镜像的工具**：做不了部署前备份、迁移判断和回滚规则，也看不到结果。
- **CI 部署演练**：`deploy/rehearse.sh` 在 runner 上用刚构建的镜像跑首次部署、升级、坏版本自动回滚、带迁移的坏版本不回滚 + 恢复，脚本出错的代价是线上停机，只有真跑才能发现。它让 CI 的 docker job 多了几分钟。
- **amd64 only**：服务器和大多数 VPS 是 amd64；arm64 要 QEMU 交叉构建，CI 时间翻倍，有需求再加。

## 落地记录
- 2026-10-21（71a–71c）：compose 日志轮转、`FRONTEND_HOST_BIND`；服务器加 2 GB swap、nginx 站点 + certbot；手动部署并导入词库。踩坑：服务器 umask 077 导致 postgres 读不到初始化脚本 → 文档写 `umask 022`。
- 2026-10-23（71e）：v0.1.0 被部署演练挡下（runner 上没有 pgvector 镜像，修复后）v0.1.1 首次经 CD 上线（CI 13 分钟 + 镜像 8.5 分钟 + 部署 2 分钟）；手动从同一 tag 重新部署 36 秒；v0.1.2 真实升级成功，回滚到 v0.1.1 约 1 分 20 秒，再前进。内存：后端 209–230 MB、前端 64–113 MB、Postgres 74–81 MB。
- 2026-10-23（71f.1–71f.3）：images job 同时推 Docker Hub；`.env.example`、README 加预构建镜像入口；`docs/deploy.md`（中英）。
- 2026-10-23（71f.4）：v0.2.0（run 39979917542）从推 tag 到部署完约 16 分钟（CI 13 分钟、镜像 1 分钟、部署 45 秒），服务器照常升级；Docker Hub 的 `0.2.0` / `0.2` / `latest` 匿名可读（amd64）。本机按 `docs/deploy.md` 用一个单独的 compose 项目从零起一套：匿名拉取约 4 分钟，启动 healthy，三份数据导入（例句 3 分 44 秒），注册、备份、恢复都正常。
