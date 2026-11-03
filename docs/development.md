# 本地开发

Python 依赖由 uv workspace 管理，前端依赖由 npm 管理。
后端代码位于 `backend/app/`，前端使用 Next.js App Router。
目录职责见 [项目结构](architecture.md)。

## Windows 启动脚本

双击根目录 `start.bat` 启动，`stop.bat` 停止。也可以在任意终端执行：

```powershell
node scripts/dev.mjs start
node scripts/dev.mjs status
node scripts/dev.mjs stop
```

单机模式使用 `start-personal.bat` 或 `node scripts/dev.mjs start --personal`；
多用户模式使用 `start-multiuser.bat` 或 `node scripts/dev.mjs start --multiuser`。
显式模式参数仅作用于本次启动，不改写 `.env`。普通 `start.bat` 遵循 `.env` 的 `APP_MODE`。
已有启动器运行其他模式时会拒绝切换，需先用 `stop.bat` 停止。`status` 输出当前模式。

单机模式通过固定的内部用户保留课程、知识、问答和模型设置的归属，不创建登录会话。
已有账号的 Cookie 在单机模式中不参与身份选择，切回多用户模式后恢复正常校验。
单机空间与已有账号之间不复制或合并数据，内部用户不能用于多用户登录。
本机模式校验连接地址、Host、Origin 与代理主机，拒绝非本机及浏览器跨站访问。
使用反向代理对外提供服务时应使用多用户模式。

加上 `--no-open` 可跳过自动打开浏览器：

```powershell
node scripts/dev.mjs start --no-open
```

启动过程会：

1. 检查 3000、8000 端口，防止误连到其他服务。
2. 用 `uv sync --locked --all-packages` 同步 Python 环境。
3. 检查项目本地 PostgreSQL，未运行时启动；首次运行会安装数据库二进制包并生成 `.env`。
4. 首次运行、前端依赖缺失或锁文件变化时执行 `npm ci`。
5. 执行 Alembic 迁移，检查 Redis；默认本机地址不可用时安装并启动项目内便携 Redis。
6. 启动 RQ Worker、Uvicorn 与 Next.js，等待页面和 API 就绪后打开网页。

开发入口由监护进程监听 `backend/app/` 的 Python 文件变化，合并短时间内的多次保存后替换后端进程树。
不依赖 Windows 隐藏窗口下无法可靠投递的 Uvicorn `CTRL_C_EVENT`，避免显示热重载却仍在处理旧版接口。

启动窗口统一显示前后端输出，日志追加保存到 `.local/logs/`。
启动失败或某个服务异常退出时，会清理本次启动的其他子进程。
停止入口通过当前仓库的控制通道通知启动器，仅结束它持有的进程树，
不会按端口查找并强制结束手动启动的进程。

启动期间保持窗口打开，使用 `Ctrl+C` 或 `stop.bat` 停止。
前后端、Redis 和 Worker 各由独立的服务监护进程持有。启动窗口关闭或启动器异常退出导致控制通道断开时，监护进程会结束自己持有的服务进程树，避免下次启动被残留服务阻塞。
旧版本留下的进程或手动启动的服务仍需单独停止，启动器不会按端口强制清理它们。
项目本地 PostgreSQL 会自动启动，`stop.bat` 停止前后端时保留数据库进程。
Redis 和 Worker 随启动脚本运行；已有 Redis 服务会复用，停止时只结束本次启动的服务。
独立运行方式及 Windows 运行文件说明见 [课件提取](extraction.md)。

## PostgreSQL

当前在 Windows 使用项目本地 PostgreSQL 16.15、pgvector 0.8.6，监听 `127.0.0.1:5432`。
Python 始终由 uv 管理，数据库二进制包使用 conda-forge 的 Windows 构建，安装时核对 micromamba 包的 SHA-256。

可以双击 `setup-postgres.bat` 单独初始化，也可以执行：

```powershell
uv run --all-packages python -m app.cli.database setup
uv run --all-packages python -m app.cli.database ensure
uv run --all-packages python -m app.cli.database info
uv run --all-packages python -m app.cli.database stop
```

`setup` 仅在 `.env` 不存在时生成连接配置，不覆盖已有配置。`ensure` 按当前配置启动或检查数据库。
服务不可用会报错，不自动切回 SQLite。

- `.local/postgres/runtime/`：PostgreSQL 与 pgvector 运行文件。
- `.local/postgres/data/`：数据库数据，重启后保留。
- `.local/postgres/runtime-packages.txt`：本机实际安装的数据库包清单。
- `.local/logs/postgres.log`：数据库日志。
- 根目录 `.env`：带随机密码的本机连接配置，不提交 Git。

业务库从空库开始，不导入旧 SQLite 账户和课件。旧数据库文件不再作为默认数据源。
使用外部或 Docker PostgreSQL 时设置 `MANAGE_LOCAL_POSTGRES=false`，由外部服务负责启动。

## 常用命令

在仓库根目录执行：

```powershell
uv sync --locked --all-packages
uv run --all-packages python -m app.cli.database ensure
uv run --all-packages alembic -c backend/alembic.ini upgrade head
uv run --all-packages uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

前端另开终端：

```powershell
npm --prefix frontend ci
npm --prefix frontend run dev
```

新增后端依赖：

```powershell
uv add --package learnflow-backend <包名>
```

更新模型后生成迁移，检查生成内容再执行：

```powershell
uv run --all-packages alembic -c backend/alembic.ini revision --autogenerate -m "describe the change"
uv run --all-packages alembic -c backend/alembic.ini upgrade head
```

## 配置

后端从仓库根目录 `.env` 读取配置，环境变量优先。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_MODE` | `multiuser` | `personal` 为免登录单机模式；前端从后端会话响应读取模式 |
| `DATABASE_URL` | 本机 PostgreSQL 的 `learnflow` 数据库 | 首次启动写入 `.env`，使用随机数据库密码 |
| `TEST_DATABASE_URL` | 首次初始化生成 `learnflow_test` 连接 | 集成测试专用，库名必须以 `_test` 结尾 |
| `MANAGE_LOCAL_POSTGRES` | 配置默认 `false`；本机初始化设为 `true` | 是否由项目工具管理 Windows 原生数据库 |
| `STORAGE_PATH` | 仓库 `storage/` | 原始课件，数据库只保存随机生成的文件 Key |
| `REDIS_URL` | `redis://localhost:6379/0` | RQ 队列连接 |
| `ALLOWED_ORIGINS` | 3000、8000 端口的 localhost / 127.0.0.1 | JSON 数组，包含前端和交互式 API 文档来源 |
| `COOKIE_SECURE` | `false` | HTTPS 环境设为 `true` |
| `MAX_UPLOAD_MB` | `25` | 后端单文件大小限制，修改时需同步调整上传界面及前端代理限制 |
| `SESSION_DAYS` | `14` | 登录有效期 |

前端默认转发到 `http://127.0.0.1:8000`。修改 `frontend/.env.local` 中的
`API_ORIGIN` 可以替换目标，参考 `frontend/.env.example`。

## 数据与文件

- 账户密码使用 Argon2 保存。数据库保存会话令牌的 SHA-256，不保存原始令牌。
- Cookie 为 HttpOnly、SameSite=Lax。课程、文件和任务接口按登录用户校验归属。
- PDF 按随机文件名落盘；展示时保留原始文件名。文件先做大小、格式、可读性及密码检查。
- 上传时在同一数据库事务中创建文件记录和处理记录。写入失败会清理刚保存的文件。
- 删除课程时级联删除文件和任务记录，再清理原始文件。清理异常会记录到日志。
- 新上传文档自动入队，任务状态依次为 `queued`、`running`、`completed` 或 `failed`。
- 自动识别结果直接存入课程知识库；保留来源、修订与识别提示，失败页面可以重试，文件始终保留。

数据库保存任务状态，Redis / RQ 调度识别工作。运行标识防止旧任务写回，重试跳过已完成页。
Windows Worker 使用 `SpawnWorker` 的项目适配，不能依赖 `fork`。

## 页面

- `/login`：账户注册和登录。
- `/`：课程列表、搜索、排序、卡片与列表切换。
- `/courses/{id}`：课程设置、PDF 上传、习题偏好、原始课件查看和删除。
- `/courses/{id}/workbooks`：课件原题筛选、手动章节分组、题目编辑、保存及本地 PDF 导出。
- `/courses/{id}/knowledge`：课程知识点、原文引用、修订、修改建议、归档和恢复。
- `/courses/{id}/chat`：课程内问答、知识与页码引用、会话历史及索引补建。
- `/courses/{id}/documents/{document_id}/extraction`：识别进度与失败重试，完成后自动进入知识库。
- `/tasks`：当前用户最近 100 条处理记录。
- `/settings`：基本资料、账号 LLM / Embedding、连接测试和索引切换进度。

页面没有预置课程。测试中出现的课程由测试账户实际创建，与日常数据库分开保存。

## 验证与范围

```powershell
uv run --locked --all-packages ruff check backend scripts
uv run --locked --all-packages ruff format --check backend scripts
uv run --locked --all-packages pytest -q
node --test scripts/service-host.test.mjs
npm --prefix frontend run format:check
npm --prefix frontend run build
npm --prefix frontend run typecheck
npm --prefix frontend run test:e2e
npm --prefix frontend run test:e2e:personal
```

后端测试在独立 PostgreSQL 测试库运行，每个用例创建随机 schema，执行真实 Alembic 迁移，
结束后只清理该 schema。覆盖会话失效、用户隔离、文件校验、事务回滚、级联删除、pgvector 检索、
问答引用、重试与版本保护；自动测试使用固定模型响应。

浏览器测试使用 Playwright 和本机 Edge，自动启动前后端，覆盖注册、登录、
课程增删改查、上传与查看文件、知识修订、公式、课程问答和手机导航。
浏览器测试使用 `learnflow_browser_test` 数据库及 `.local/browser-storage/`，预览截图位于 `.local/previews/`。
测试前端使用 `.next-e2e/` 独立构建目录，可与日常开发服务同时运行。
单机浏览器测试使用相同的独立端口和测试库，需与多用户浏览器测试依次执行。
覆盖免登录、上传课件、知识库、问答、保存模型设置、浏览器重开与登录页自动跳转。
浏览器测试后端实现位于 `backend/tests/browser_server.py`，由 `scripts/test-backend.mjs` 启动。
Ruff、pytest 配置统一放在根目录 `pyproject.toml`，Prettier 使用根目录配置。
GitHub Actions 执行后端检查、前端格式与构建，以及 Windows / Linux 启动器测试。
课程知识库的边界、同步机制和当前范围见 [课程知识库](knowledge-base.md)。
修改建议的 LLM 审查、来源读取和版本保护见 [模型处理修改建议](proposal-review.md)。

PostgreSQL / pgvector、Redis / RQ 已完成本机服务联调。
向量模型已接入请求客户端，可设置系统默认或从账号设置保存个人模型，配置与实测命令见 [模型配置](models.md)。
生成模型 `qwen3.8-flash` 已接入请求客户端，并通过真实普通回复和 JSON Schema 输出验证。
已接入课件逐页图像识别、知识与原有题目提取及自动入库，以及当前知识的后台向量索引和课程问答。
问答运行方式、索引补建、真实固定文本验证及当前限制见 [课程问答](chat.md)。
自动分章、原题选题、区域核对和两种 PDF 打印见[课件做题本](workbooks.md)；跨页题干自动合并尚未接入。
账号模型配置和 API Key 主密钥的保存与备份见 [账号设置](account-settings.md)。
