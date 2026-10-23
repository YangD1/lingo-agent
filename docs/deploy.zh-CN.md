# 部署

[English](deploy.md)

怎样把 lingo-agent 跑在一台低配 Linux 服务器上，前面加 HTTPS，并做好备份。主线用每个版本发布在 Docker Hub 上的预构建镜像；从源码构建也一样，只是改用 `make up`。最后一节[持续部署](#可选持续部署到自己的服务器)是可选的：在你 fork 的仓库里推一个 tag，就自动部署到你的服务器。为什么这样设计见 [ADR 0063](decisions/0063-deployment.md)。

下文域名用 `lingo.example.com`，代码目录用 `/opt/lingo-agent`，换成你自己的。

## 需要什么

- 一台 Linux 服务器（amd64；暂时没有 arm64 镜像），装好 Docker 和 Compose v2、`git`、`make`、`openssl`。
- **内存**。三个容器的上限分别是 512 MB（Postgres）、768 MB（后端）、384 MB（前端）。在一台 2 核、约 1.6 GB 内存的服务器上实测，运行起来后后端约 210–230 MB、前端 65–115 MB、Postgres 75–80 MB。一次性导入例句时要再多用约 800 MB，持续几分钟。内存 2 GB 或更少的服务器先加 swap（2 GB 就够）：

  ```bash
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
  sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
  ```

- 一个已经解析到这台服务器的域名，开放 80 和 443 端口，再加一个做 HTTPS 的反向代理。本文用 nginx + certbot；换别的代理也行，只要做到[下面模板](#5-用-nginx-加-https)里那几件事。
- 模型的 API key **不属于**部署：每个用户在应用的设置页里自己填，加密存库。

不要在这么小的服务器上构建镜像：构建前端需要的内存比它的总内存还多。用预构建镜像，或者在别的机器上构建后推到镜像仓库。

## 首次安装

### 1. 取对应版本的代码

检出你要运行的那个版本。compose 文件和 `config/` 来自代码目录，必须和镜像版本一致：

```bash
umask 022   # 原因见下
sudo mkdir -p /opt/lingo-agent && sudo chown "$USER" /opt/lingo-agent
git clone --branch v0.2.0 https://github.com/YangD1/lingo-agent.git /opt/lingo-agent
cd /opt/lingo-agent
make env    # 生成 .env（权限 600），带新的加密主密钥和 JWT 密钥
```

默认 umask 是 `077` 的服务器上，`umask 022` 很关键：Postgres 容器用另一个用户运行，建库时要读代码目录里的 `docker/postgres/init/`。读不到的话，第一次启动会留下一个初始化了一半的数据库（见[排错](#排错)）。

### 2. `.env` 里的生产配置

改这几行（`.env` 里的注释逐条说明了用途）：

```bash
APP_ENV=prod
PROVIDERS_CONFIG=config/providers.prod.yaml
# 只在第一次建库时读取：第一次启动前就要设好。
POSTGRES_PASSWORD=<openssl rand -hex 24 的输出>
# 只允许本机的反向代理访问前端。
FRONTEND_HOST_BIND=127.0.0.1
# 预构建镜像；IMAGE_TAG 是你检出的版本号，不带 “v”。
BACKEND_IMAGE=youngdeezh/lingo-agent-backend
FRONTEND_IMAGE=youngdeezh/lingo-agent-frontend
IMAGE_TAG=0.2.0
```

只要服务器有别人在用，就保持 `PROVIDER_ALLOW_PRIVATE_NETWORKS=false`：它防止租户把模型连接指向你的内网。容器不读 `.env` 里的 `DATABASE_URL`（它们的数据库地址写死在 `docker-compose.yml` 里），这行不用改。

`APP_ENV=prod` 拒绝短于 32 字节的 `JWT_SECRET`（`make env` 生成的就是 32 字节），而且登录 cookie 只经 HTTPS 发送，所以用 `http://` 登录会失败，这是有意的。

**现在就备份 `.env`**，放在这台服务器以外的地方。其中的 `CREDENTIALS_ENCRYPTION_KEYS` 加密了存在数据库里的模型 API key；没有它，数据库备份里的这些 key 就没用了（见[备份](#备份)）。

### 3. 启动

```bash
docker compose pull
docker compose up -d --no-build --wait
docker compose ps      # postgres、backend、frontend 都是 running (healthy)
curl -sI http://127.0.0.1:3000 | head -n 1
```

后端每次启动都会执行数据库迁移。想从源码构建而不是拉镜像：镜像那几行保持默认值，运行 `make up`。

### 4. 导入词库数据（一次）

词汇页、定级测试和单词卡片需要把三份开放数据导入数据库。在服务器上，先在宿主机下载，再用一次性容器导入。用 `docker compose run --rm`，不要用 `exec`：单独的容器有自己的内存上限，不会把正在运行的后端挤爆 768 MB。

```bash
mkdir -p data/tatoeba data/simplewiktionary

# ECDICT 词表（MIT），固定在一个提交上；导入前先校验文件。
curl -fL -o data/ecdict.csv \
  https://raw.githubusercontent.com/skywind3000/ECDICT/bc015ed2e24a7abef49fc6dbbb7fe32c1dadaf8b/ecdict.csv
echo "1a6947e04785db63613a92e14903cdae7954f7e84860b10e68e5c7cbb3f9c3cf  data/ecdict.csv" | sha256sum -c

# Tatoeba 例句（CC BY 2.0 FR），每周更新。
for f in eng/eng_sentences.tsv.bz2 cmn/cmn_sentences.tsv.bz2 cmn/cmn-eng_links.tsv.bz2; do
  curl -fL -o "data/tatoeba/${f#*/}" "https://downloads.tatoeba.org/exports/per_language/$f"
done

# Simple English Wiktionary 义项（CC BY-SA）。
curl -fL -o data/simplewiktionary/simplewiktionary-latest-pages-articles.xml.bz2 \
  https://dumps.wikimedia.org/simplewiktionary/latest/simplewiktionary-latest-pages-articles.xml.bz2

run() { docker compose run --rm --no-deps -T -v "$PWD/data:/data:ro" backend python -m "$@"; }
run app.services.vocab.import_ecdict --csv /data/ecdict.csv     # 约 15 秒，约 38,000 词
run app.services.vocab.import_tatoeba --dir /data/tatoeba       # 约 3 分钟，约 800 MB
run app.services.vocab.import_simplewiktionary \
  --file /data/simplewiktionary/simplewiktionary-latest-pages-articles.xml.bz2   # 约 10 秒
```

按这个顺序运行（后两个要挂到 ECDICT 导入的词上）。每个都可以安全地重复运行，比如想用新一周的 Tatoeba 导出。`data/` 不进 git，导完可以删掉。

### 5. 用 nginx 加 HTTPS

新建 `/etc/nginx/sites-available/lingo.example.com`（没有 `sites-available` 的发行版放到 `/etc/nginx/conf.d/lingo.example.com.conf`）：

```nginx
# lingo-agent: nginx terminates HTTPS and forwards to the frontend on 127.0.0.1:3000.
map $http_upgrade $lingo_connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80;
    listen [::]:80;
    server_name lingo.example.com;

    # Largest attachment is a 20 MB document.
    client_max_body_size 25m;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        # Overwrite, don't append: per-IP rate limits read X-Forwarded-For (ADR 0035).
        proxy_set_header X-Forwarded-For   $remote_addr;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        # Realtime voice calls are WebSockets.
        proxy_set_header Upgrade           $http_upgrade;
        proxy_set_header Connection        $lingo_connection_upgrade;
        # Chat replies stream (SSE); pass bytes through as they arrive.
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    access_log /var/log/nginx/lingo.access.log;
    error_log  /var/log/nginx/lingo.error.log;
}
```

然后启用并申请证书；certbot 会加上 `listen 443 ssl` 和 HTTP → HTTPS 跳转，之后自动续期：

```bash
sudo ln -s /etc/nginx/sites-available/lingo.example.com /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d lingo.example.com
```

各项的作用（换别的代理时对照）：

| 配置 | 不配会怎样 |
|---|---|
| `X-Forwarded-For $remote_addr`（覆盖） | Next 会把浏览器自己带的这个头原样转给后端，谁都能伪造 IP，绕过登录和注册的按 IP 限流。Caddy 的 `reverse_proxy` 默认就会覆盖。 |
| `FRONTEND_HOST_BIND=127.0.0.1` | 绕过代理、直接访问 3000 端口也能用，问题同上。 |
| `Upgrade` / `Connection` | 实时通话连不上。 |
| `proxy_buffering off`、较长的超时 | 聊天回复不再逐字出现，而是写完才一次性出来；长回复和通话会被中途断开。 |
| `client_max_body_size` | 超过 1 MB 的附件报 413。 |

打开 `https://lingo.example.com`，注册第一个账号，在设置页加一个模型连接。确认 `http://` 会跳到 `https://`，并且外部访问不到 3000、8000、5433 端口（在服务器上 `ss -tlnp`，这三个应该只监听 `127.0.0.1`）。

## 备份

`deploy/backup.sh [标签]`（或 `make backup`）用 `pg_dump -Fc` 把数据库导出到 `backups/<UTC 时间>_<标签>.dump`，检查能读回，只保留最新的 14 份（`LINGO_BACKUP_KEEP`）。用 cron 每天备份一次（`crontab -e`，用 `docker` 组里的用户）：

```cron
30 4 * * * cd /opt/lingo-agent && deploy/backup.sh daily >/dev/null
```

和数据库放在同一块盘上的备份，服务器没了它也没了：定期把 `backups/` 复制到别处（`rsync`、对象存储……）。

**`.env` 要单独备份。** 备份里的模型 API key 是用 `CREDENTIALS_ENCRYPTION_KEYS` 加密的。没有同一份密钥，恢复出来的数据库能用，但存着的 API key 全都解不开，用户要重新填。`JWT_SECRET` 没那么要紧：丢了只是所有人要重新登录。不要把 `.env` 和备份放在一起：两样都拿到的人就拿到了 API key。

**恢复**用 `make restore FILE=backups/<文件名>.dump`（或 `deploy/restore.sh <文件>`）。它会先确认，再备份当前数据库（`before_restore`），停掉后端和前端，在一个事务里恢复（恢复失败时数据库保持原样），最后重新启动。正在运行的版本必须和备份的表结构一致：见[回滚](#回滚)。

## 升级

先看版本说明里有没有要手动做的事，然后：

```bash
cd /opt/lingo-agent
deploy/backup.sh before_0.2.1
git fetch --tags && git checkout v0.2.1
sed -i 's/^IMAGE_TAG=.*/IMAGE_TAG=0.2.1/' .env
docker compose pull
docker compose up -d --no-build --wait
```

后端启动时迁移数据库。`.env.example` 加了新配置项时会用默认值，用 `diff .env.example .env` 能看到。从源码构建的：`git checkout` 新 tag 后 `make up`。

### 回滚

能不能直接退回去，取决于新版本有没有改表结构。升级前先记下每个版本需要的表结构版本：

```bash
docker compose run --rm --no-deps -T --entrypoint alembic backend heads
```

升级后再运行一次。输出一样的话，检出旧 tag、把 `IMAGE_TAG` 改回去，再跑同样的 `pull` 和 `up` 就行。输出变了的话，旧版本不一定能在新表结构上运行：检出旧 tag、改回 `IMAGE_TAG`、`docker compose pull`，再恢复升级前的那份备份：

```bash
make restore FILE=backups/<时间>_before_0.2.1.dump
```

数据库和旧镜像对上之后，`restore.sh` 会用旧镜像重新启动后端和前端。升级之后、恢复之前写入的数据会丢失。

## 可选：持续部署到自己的服务器

[`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) 是本项目部署自己服务器的方式，fork 之后也能用。推一个 `v*` tag：先对这个提交跑 CI，再把后端和前端镜像构建一次、推到每个配置了的镜像仓库；如果配置了服务器，再经 SSH 通知服务器切到这个提交。每一部分都只在配置齐了时才运行，所以什么都没配的 fork 只跑 CI。

从旧的 tag 手动运行这个 workflow 就是回滚：它的镜像还在仓库里，会跳过 CI 和构建，直接部署（约一分钟）。

### 一次部署做了什么

服务器的所有东西都从一个**私有镜像仓库**拉：两个应用镜像，加一个很小的“发布镜像”，里面是这个提交的 compose 文件、`config/`、Postgres 初始化脚本和 `deploy/` 脚本。SSH 密钥只能执行一条命令 `deploy <40 位提交号>`，由服务器上的 [`deploy/deploy-entry`](../deploy/deploy-entry) 强制；它不能上传文件，也不能开 shell。所以密钥泄露了，最多也只能重新部署 CI 已经构建过的东西。

服务器上的 `deploy/deploy.sh`：

1. 拉镜像（失败则什么都不变）；
2. 比较新旧后端镜像需要的表结构版本（`alembic heads`）；
3. 备份数据库（`backups/<时间>_before_<提交号>.dump`）；
4. 启动新版本，等所有健康检查通过；
5. 成功：`current` 指向新版本，只保留最新的五个版本目录；
6. 失败：**表结构没变**，就重新启动上一个版本；**变了**，就停在新版本上（旧代码不一定能在新表结构上运行），这次运行标为失败，并打印用第 3 步那份备份恢复的 `restore.sh` 命令。

Actions 日志里只打印步骤和结果，因为公开仓库的日志是公开的。详细输出在服务器的 `logs/` 里，每次部署在 `deployed.log` 里记一行。

服务器上的目录（`LINGO_ROOT`，这里是 `/srv/lingo-agent`）：

```
releases/<commit>/   一个版本：compose 文件、config/、deploy/、.env -> ../../shared/.env
current -> releases/<commit>
shared/.env          配置和密钥的唯一一份
shared/postgres-init docker/postgres/init 的固定副本
backups/  logs/  bin/deploy-entry  deployed.log
```

每个版本一个目录而不是一个代码目录，是为了切回去只需要从另一个目录启动。compose 的项目名是固定的（`lingo-agent`），所以无论从哪个目录启动，数据库卷都是同一个，包括之前用代码目录部署时的那个。

### 服务器准备（一次）

1. **镜像仓库**。任何服务器拉得到、GitHub 推得上去的仓库都行。在同一个命名空间下建 `backend`、`frontend`、`release`、`pgvector` 四个仓库（私有的就行；workflow 还会把固定版本的 pgvector 镜像复制一份过去，给连不上 Docker Hub 的服务器用）。
2. **部署用户**。`docker` 组的成员约等于这台机器的 root，所以密钥要锁死只能执行一条命令：

   ```bash
   sudo useradd --create-home --groups docker --shell /bin/bash deploy
   sudo passwd -l deploy
   sudo install -d -o deploy -g deploy /srv/lingo-agent/{shared,releases,bin}
   sudo install -d -o deploy -g deploy -m 700 /srv/lingo-agent/{backups,logs}
   ```

3. **配置**。把你的 `.env`（或者用 `make env` 新生成一份，再按上面改成生产配置）放到 `/srv/lingo-agent/shared/.env`，权限 600、属主 `deploy`，再加上：

   ```bash
   BACKEND_IMAGE=<仓库地址>/<命名空间>/backend
   FRONTEND_IMAGE=<仓库地址>/<命名空间>/frontend
   RELEASE_IMAGE=<仓库地址>/<命名空间>/release
   POSTGRES_IMAGE=<仓库地址>/<命名空间>/pgvector:pg16
   POSTGRES_INIT_DIR=/srv/lingo-agent/shared/postgres-init
   ```

   不用写 `IMAGE_TAG`：每个版本会把它设成自己的提交号。把 `docker/postgres/init/` 复制到 `shared/postgres-init/`（要让其他用户可读：`chmod -R go+rX`）。
4. **入口和密钥**。装好入口脚本（以后每次部署成功都会换成新版本里的那份），再生成一把只能运行它的密钥：

   ```bash
   sudo install -o deploy -g deploy -m 755 deploy/deploy-entry /srv/lingo-agent/bin/
   ssh-keygen -t ed25519 -N '' -C lingo-deploy -f ./lingo-deploy   # 在你自己的电脑上
   ```

   在 `~deploy/.ssh/authorized_keys`（目录 700、文件 600）里加一行：

   ```
   restrict,command="/srv/lingo-agent/bin/deploy-entry" ssh-ed25519 AAAA... lingo-deploy
   ```

   确认 `ssh -i lingo-deploy deploy@<服务器> ls` 被拒绝，然后私钥只放进下面的 GitHub secret。
5. 用部署用户**登录镜像仓库**，让它能拉镜像：`sudo -iu deploy docker login <仓库地址>`。
6. **每日备份**。[`deploy/systemd/`](../deploy/systemd) 里有 service 和 timer（每天 04:30，以 `deploy` 身份运行）：

   ```bash
   sudo cp deploy/systemd/lingo-backup.* /etc/systemd/system/
   sudo systemctl daemon-reload && sudo systemctl enable --now lingo-backup.timer
   ```

   它运行的是 `current/deploy/backup.sh`，所以首次部署之后才开始生效。

### GitHub 配置

建一个叫 `production` 的环境（Settings → Environments），只允许匹配 `v*` 的 tag 部署到它，下面这些都放在这个环境里：

| 类型 | 名字 | 值 |
|---|---|---|
| variable | `ACR_REGISTRY` | GitHub 推送用的仓库地址（名字是历史原因，任何仓库都行） |
| variable | `ACR_NAMESPACE` | 那四个仓库所在的命名空间 |
| secret | `ACR_USERNAME`、`ACR_PASSWORD` | 有推送权限的仓库账号 |
| variable | `DEPLOY_USER` | `deploy` |
| secret | `DEPLOY_HOST`、`DEPLOY_PORT` | 服务器地址和 SSH 端口 |
| secret | `DEPLOY_SSH_KEY` | 第 4 步的私钥 |
| secret | `DEPLOY_KNOWN_HOSTS` | 服务器的 host key 那一行，比如 `ssh-keyscan -p <端口> <地址>` 的输出；和服务器上的指纹核对一遍 |
| variable | `DOCKERHUB_NAMESPACE` | 可选：同时在这里发布公开镜像 |
| secret | `DOCKERHUB_TOKEN` | 有写权限的 Docker Hub access token（配合 `DOCKERHUB_NAMESPACE`） |

`DEPLOY_USER` 故意用 variable：Actions 会把日志里所有和 secret 值相同的文字替换成 `***`，secret 设成 “deploy” 的话，日志里所有 deploy 这个词都没了。服务器地址和端口放 secret，公开日志里就看不出服务器在哪。

然后推一个 tag：

```bash
git tag v0.2.0 && git push origin v0.2.0
```

第一次运行约 25 分钟（CI 约 13 分钟、镜像约 8 分钟、部署约 2 分钟）；有构建缓存后镜像约一分钟。服务器第一次部署时没有上一个版本可以回退。要把已有的代码目录部署迁过来：在第一次运行前，到旧目录里 `docker compose down`（数据库卷会保留）。

### GitHub 用不了时

Actions 用不了时，手动做 workflow 做的事：构建并推送 `backend`、`frontend`、`release`（在仓库根目录 `docker build -f deploy/release.Dockerfile .`），标签用完整的提交号；然后在服务器上用管理员身份运行：

```bash
sudo -u deploy /srv/lingo-agent/bin/deploy-entry deploy <40 位提交号>
```

`deploy/rehearse.sh` 用本地镜像把服务器端完整跑一遍（首次部署、升级、自动回滚、迁移后失败再恢复）；CI 每次推送都会运行它。

## 排错

- **第一次启动后 Postgres 反复重启，或者后端登不上数据库。** 多半是初始化脚本读不到（克隆时 `umask 077`）：`chmod -R go+rX docker/postgres/init`。Postgres 只在建库时运行这些脚本，所以如果是**全新的空安装**，还要删掉建了一半的数据卷（`docker compose down -v`，会删除数据库）。第一次启动后再改 `POSTGRES_PASSWORD` 也是一样：对已有的数据库不起作用。
- **登录请求成功了，但还是没登录上。** `APP_ENV=prod` 只经 HTTPS 发 cookie。通过代理用 `https://` 打开。
- **所有人一起被提示“操作太频繁”，或者限流从来不生效。** 代理没有覆盖 `X-Forwarded-For`，或者前端的 3000 端口能被直接访问。
- **回复一次性出来。** 代理开着响应缓冲（`proxy_buffering off`）。
- **`docker compose pull` 超时。** 有些网络连不上 Docker Hub。在 Docker 里配镜像加速，或者用上面的持续部署，它会把镜像复制到服务器连得上的仓库。
- **导入例句时进程被杀。** 它要约 800 MB；加 swap，并用 `docker compose run` 而不是 `exec`。
- **其他问题。** `docker compose ps` 看健康状态，`docker compose logs --tail 200 backend` 看报错。
