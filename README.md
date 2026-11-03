# LearnFlow

课程 PDF 管理、知识提取、课程问答与原题做题本。前后端放在同一个仓库，业务数据库和向量检索使用 PostgreSQL + pgvector。

## 当前功能

- **课程与课件**：账号注册、登录、课程管理、PDF 上传、原文件查看、处理进度和失败重试。
- **知识库**：逐页提取知识点、公式、例题和习题；正文与原文引用分开保存，支持 Markdown、LaTeX、修订历史和归档。
- **修改建议**：经用户确认后由模型结合课件审查，返回意见和处理结果；更新时检查知识版本。
- **课程问答**：LangGraph 编排按需检索、回答和引用校验；支持多轮记录、图片、一级分支和选中文字追问。
- **做题本**：同一课程的多个课件可合并选题，按章节或页码限定范围，自动整理原题并去重；支持独立编辑、原页裁片和 A4 PDF 导出。
- **账号模型**：每个账号配置一套 LLM 和 Embedding，支持百炼、硅基流动与 OpenAI 兼容接口，LLM 另支持 DeepSeek。更换向量模型会建立新索引，完成后再切换。

知识与课件按用户、课程隔离。原文、知识正文、向量和问答记录保存在本地；调用模型时，相关文本或页面图片会发往配置的模型服务。

**尚未实现**：AI 新题生成、跨页题干自动合并、知识笔记 PDF 导出、分支总结回写与合并。详细计划见 [todo.md](todo.md)。

## 技术栈

| 部分 | 技术 |
| --- | --- |
| 前端 | Next.js App Router、React、TypeScript |
| 编辑与公式 | Markdown、React Markdown、KaTeX |
| 后端 | FastAPI、SQLAlchemy、Alembic |
| 数据与检索 | PostgreSQL、pgvector |
| 后台任务 | Redis、RQ SpawnWorker，支持 Windows |
| 模型编排 | LangGraph、PostgreSQL checkpointer |
| PDF | PyMuPDF；Playwright 排版与导出 |
| 依赖管理 | uv workspace、npm lockfile |

## 仓库结构

```text
LearnFlow/
├── backend/
│   ├── app/
│   │   ├── api/          # 路由和归属校验
│   │   ├── core/         # 配置、数据库、会话与凭据
│   │   ├── models/       # SQLAlchemy 模型
│   │   ├── schemas/      # 请求与响应结构
│   │   ├── services/     # 提取、检索、模型调用和做题本等业务
│   │   ├── workers/      # Redis / RQ 执行器
│   │   └── cli/          # 数据库、队列与诊断命令
│   ├── alembic/          # 数据库迁移
│   ├── tests/            # 后端测试和浏览器测试用服务
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── app/          # 路由、布局和错误边界
│   │   ├── features/     # 按业务组织的页面、组件、类型和样式
│   │   ├── components/   # 公共界面与导航
│   │   └── lib/          # 请求和通用工具
│   ├── tests/            # Playwright 端到端测试
│   ├── scripts/          # 本机 PDF 排版
│   └── package.json
├── scripts/              # 开发启动、服务监护和测试启动
├── docs/                 # 架构、开发环境和功能说明
├── .github/workflows/    # 持续集成
├── pyproject.toml        # uv workspace、Ruff 和 pytest 配置
├── uv.lock
├── start.bat
├── stop.bat
└── docker-compose.yml
```

保留单仓库结构，前后端各自维护源码、依赖和测试，方便接口、迁移和页面同步提交。具体边界见 [架构说明](docs/architecture.md)。

## 本地运行

开发环境使用 Python 3.13、uv 和 Node.js 20.9 以上。Windows 上 PDF 导出默认使用已安装的 Microsoft Edge。

### Windows 启动

双击根目录 `start.bat`，就绪后自动打开 <http://127.0.0.1:3000>；停止时双击 `stop.bat`。

首次启动会同步依赖，准备项目本地 PostgreSQL + pgvector 和 Redis，并执行数据库迁移。无需预先激活虚拟环境或安装 Docker。
Python 环境统一位于根目录 `.venv/`。启动窗口意外关闭后，监护进程会清理它持有的前后端和队列进程；数据库保持运行。

后端 API 文档：<http://127.0.0.1:8000/docs>。日志位于 `.local/logs/`。
后端代码修改由启动器自动重载，不依赖 Windows 隐藏窗口中的 Uvicorn 信号处理。

### 手动运行 / Docker 数据库

从仓库根目录执行：

```powershell
Copy-Item .env.example .env
docker compose up -d
uv sync --locked --all-packages
uv run --all-packages python -m app.cli.database setup
uv run --all-packages alembic -c backend/alembic.ini upgrade head
npm --prefix frontend ci
```

分别在终端启动服务：

```powershell
uv run --all-packages uvicorn app.main:app --host 127.0.0.1 --port 8000
uv run --all-packages python -m app.workers.main
npm --prefix frontend run dev
```

已有 `.env` 时保留原配置。切换本机或 Docker PostgreSQL 前，应先停止另一套数据库并核对连接地址。
业务数据库不回退 SQLite，也不迁移旧 SQLite 账户和课件。更多运行方式见 [本地开发](docs/development.md)。

## 模型设置

登录后进入侧栏“账号设置”，填写自己的 LLM、Embedding 模型名称、基础地址和 API Key，并使用固定样本测试连接。
课件识别及聊天图片需要支持视觉的 LLM。更换 Embedding 时应填写实际向量维度；索引建成前保留原配置。

系统默认模型放在本机 `.env`。账号密钥加密存入数据库，加密主密钥由环境变量或 `.local/model-encryption.key` 管理。
`.env`、密钥、本地数据库、上传文件、缓存、测试截图和构建产物均不提交。

字段说明见 [账号设置](docs/account-settings.md)，模型适配与诊断见 [模型配置](docs/models.md)。

## 开发检查

后端集成测试需要 PostgreSQL + pgvector；`TEST_DATABASE_URL` 必须指向名称以 `_test` 结尾的独立测试库。
每个用例使用独立 schema，结束后清理。浏览器测试使用独立数据库和 3100、8001 端口，不读取用户课件。

```powershell
uv run --locked --all-packages ruff check backend scripts
uv run --locked --all-packages ruff format --check backend scripts
uv run --locked --all-packages pytest -q
node --test scripts/service-host.test.mjs
npm --prefix frontend run format:check
npm --prefix frontend run build
npm --prefix frontend run typecheck
npm --prefix frontend run test:e2e
```

Linux 上运行 PDF 测试或导出前，需在 `frontend/` 执行 `npx playwright install --with-deps chromium`，并安装中文字体。
GitHub Actions 检查后端、前端构建和 Windows / Linux 启动监护逻辑；模型测试使用固定响应，不需要真实 API Key。

## 功能文档

- [知识库与数据隔离](docs/knowledge-base.md)
- [课件提取与公式处理](docs/extraction.md)
- [修改建议处理](docs/proposal-review.md)
- [课程问答与分支](docs/chat.md)
- [原题做题本与 PDF](docs/workbooks.md)

## License

尚未声明开源许可。
