# 项目结构

采用单仓库：根目录管理开发环境、启动入口、代码检查和文档，前后端各自维护源码、依赖和测试。
本机数据库、上传文件与运行日志由忽略规则排除，不参与源码提交。

```text
LearnFlow/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── router.py        # 汇总 /api 路由
│   │   │   ├── dependencies.py  # 资源归属检查
│   │   │   ├── auth.py
│   │   │   ├── courses.py
│   │   │   ├── documents.py
│   │   │   ├── tasks.py
│   │   │   ├── knowledge.py
│   │   │   ├── chat.py         # 会话、问答、引用与索引状态
│   │   │   ├── account.py      # 资料、账号模型连接与索引切换
│   │   │   ├── workbooks.py    # 原题筛选、做题本快照和 PDF 导出
│   │   │   ├── document_structure.py # 章节、整理进度、裁片和图片鉴权
│   │   │   └── extraction.py   # 逐页识别、进度查询及自动入库
│   │   ├── core/               # 配置、数据库连接、会话验证
│   │   ├── models/             # 按业务拆分的 SQLAlchemy 模型
│   │   ├── schemas/            # 按业务拆分的请求与响应结构
│   │   ├── services/           # 文件存储等业务能力
│   │   ├── workers/            # RQ SpawnWorker 及 Windows 子进程适配
│   │   ├── cli/                # 数据库、队列与模型诊断命令
│   │   └── main.py             # 应用装配、日志、中间件与异常处理
│   ├── alembic/
│   ├── tests/                  # 集成测试及 browser_server.py 测试服务
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── app/                # 页面路由、布局、元数据与错误边界
│   │   ├── features/
│   │   │   ├── auth/           # 登录页面、用户状态、用户类型
│   │   │   ├── courses/        # 课程页面、表单、课程状态与类型
│   │   │   ├── documents/      # 文件上传、识别进度与失败重试
│   │   │   ├── knowledge/      # 知识点、原文引用、修订与修改建议
│   │   │   ├── chat/           # 课程问答、分支、来源与会话历史
│   │   │   ├── account/        # 账号资料、模型表单与重建进度
│   │   │   ├── workbooks/      # 原题选题、分组编辑和导出
│   │   │   ├── chapters/       # 章节范围编辑与后台整理状态
│   │   │   └── tasks/          # 任务记录页面与类型
│   │   ├── components/
│   │   │   ├── layout/         # 工作空间外壳与导航
│   │   │   └── ui.tsx          # 弹窗、提示、加载状态
│   │   └── lib/
│   │       ├── http.ts         # 通用请求、错误处理
│   │       └── format.ts       # 日期和文件大小格式化
│   ├── tests/
│   ├── scripts/render-workbook.mjs # 无网络的本机 PDF 排版
│   └── package.json
├── scripts/
│   ├── dev.mjs                 # 开发服务启动、状态查询和停止
│   ├── service-host.mjs        # 进程树管理与后端源码变更重载
│   ├── service-host.test.mjs   # 监护进程测试
│   └── test-backend.mjs        # 浏览器测试的独立后端环境
├── docs/
├── .github/workflows/ci.yml    # 后端、前端和启动器检查
├── start.bat
├── start-personal.bat
├── start-multiuser.bat
├── stop.bat
├── setup-postgres.bat
├── pyproject.toml              # uv workspace、开发依赖、Ruff 与 pytest
├── uv.lock
└── docker-compose.yml
```

## 后端边界

- `api/` 接收请求、验证归属、调用服务并组装响应。每个模块维护自己的路由，统一在 `router.py` 注册。
- `models/` 描述持久化结构，`schemas/` 描述接口结构，避免互相混用。新增模型必须在 `models/__init__.py` 导入，供 SQLAlchemy 和 Alembic 发现。
- `core/` 放多个业务模块共用的基础能力。它不依赖路由。
- `core/personal.py` 管理单机身份和本机访问边界。两种模式仍使用 `CurrentUser` 和相同归属检查；`/api/auth/me` 告知前端当前模式，不依赖前端构建变量切换认证。
- `services/` 放文件处理、解析、模型调用等可复用业务逻辑。业务复杂后再拆分具体服务，不为简单查询增加空的中间层。
- `workers/` 执行后台任务，复用服务层；数据库保留任务状态，Redis 保存队列。

对外接口路径保持稳定，例如课程文件仍通过 `/api/courses/{id}/documents` 上传。
模型目录调整没有改变原有表名和字段。新增迁移 `0002` 创建课程知识、来源、修订和检索表，
具体数据边界见 [课程知识库](knowledge-base.md)。

问答由 `services/retrieval.py` 检索、`chat_generation.py` 调用模型、`chat.py` 管理会话与版本校验。
`vector_index.py` 复用现有 Redis 队列后台生成向量；事务提交后才入队。迁移 `0005` 创建会话与消息表，
并补充索引元数据。`chat_graph.py` 用 LangGraph 编排问答，`chat_checkpoints.py` 通过 PostgresSaver
持久化状态并校验当前运行标识；`chat_branches.py` 负责分支创建和不可变上下文快照。
`chat_intent.py` 使用账号 LLM 判断本轮是否需要检索，`chat_context.py` 校验已有引用并提供聊天回顾上下文。
`query_embeddings.py` 提供按用户、课程及完整模型配置隔离的短期进程缓存，课程删除时同步清理。
`chat_images.py` 解码并规范图片，`chat_vision.py` 提供题干、公式与图表内容识别，`chat_graph.py` 继续判断是否需要检索。
迁移 `0009` 新增图片消息：处理后的图片二进制保存在 `chat_images`，字段延迟加载，与消息外键级联删除；
接口只返回元数据，通过当前账号归属检查后才能读取图片。图片二进制不写入 LangGraph checkpoint。
迁移 `0007` 添加 checkpoint 和会话关联表，`0008` 添加一级分支关系和快照。
主对话、分支分别使用独立 thread_id；删除会话通过外键级联清理业务消息与 checkpoint。
详细流程见 [课程问答](chat.md)。
`account_models.py` 解析账号配置，`account_index.py` 管理并行索引和账号级切换，
`core/model_runtime.py` 隔离每次请求使用的模型设置，`core/model_secrets.py` 管理凭据加密。
迁移 `0006` 不添加课程级模型绑定，详细规则见 [账号设置](account-settings.md)。

`workbooks.py` 从提取记录筛选原题并保存独立的做题本快照；迁移 `0010` 增加 `workbooks`。
`workbook_pdf.py` 将快照通过标准输入交给前端目录中的 Node 排版程序，
使用本地 Markdown、KaTeX 与 Playwright 渲染 PDF，不调用前端 HTTP 页面或模型。
Windows 使用 Edge；同一进程限制并发和超时，不公开保存导出文件。详见 [课件做题本](workbooks.md)。

迁移 `0011` 添加章节、文档整理状态、题目标签、区域与图片快照。
`chapters.py` 按目录、标题或账号模型识别章节；`document_organization.py` 在 RQ 中识别题目标签与区域建议，
写回校验运行编号与版本。`exercise_layouts.py` 验证框选坐标并生成本地裁片；
`workbook_assembly.py` 理解组卷要求、校验候选编号和配额，并按知识覆盖选题。
`workbook_scope.py` 校验来源课件归属，并为手动查找与自动整理应用同一组课件、章节、页码条件。
`workbook_images.py` 只装配当前本册已保存的图片快照，保真打印缺图时明确失败。

## 前端边界

- `app/` 的页面文件尽量保持简短，导入相应功能页面，配置页面标题。
- `features/<功能>/` 放该功能的界面、状态和类型。专用请求也放在功能内，例如 PDF 上传。
- `components/` 只放跨功能复用的界面。课程表单属于课程功能，上传表单属于文档功能。
- `lib/` 只放通用工具，不集中存放全部业务类型。
- 使用 `@/` 导入，跨功能只引用必要的类型或组件，避免依赖其他功能的内部状态。
- 功能样式随功能存放。章节编辑使用 `features/chapters/chapter-organizer.css`，课件详情使用 `features/documents/document-detail.css`，不依赖做题本的样式文件。

部分问答、知识库和做题本组件以及全局样式较长，后续按独立交互拆分。新增功能沿用现有边界，尚未实现的功能不提前创建空模块。

## 检查与测试

- 根目录 `pyproject.toml` 统一维护 Ruff、pytest 和 uv workspace 配置；后端业务依赖在 `backend/pyproject.toml`。
- `.editorconfig`、`.gitattributes` 和 Prettier 配置约定缩进、换行与前端格式。`uv.lock` 和 `frontend/package-lock.json` 一并提交。
- 后端测试位于 `backend/tests/`，只能连接名称以 `_test` 结尾的 PostgreSQL 测试库，每个用例使用独立 schema。
- 浏览器用例位于 `frontend/tests/`；`scripts/test-backend.mjs` 启动 `backend/tests/browser_server.py`，使用独立测试库和端口。
- GitHub Actions 检查后端测试与格式、前端格式与构建、Windows / Linux 服务监护进程。浏览器回归在本机执行。

完整检查命令见 [README](../README.md#开发检查)。

## 本机数据库

`backend/app/cli/database.py` 负责 Windows 原生 PostgreSQL 的安装、初始化、启动、停止和状态查询。
运行文件及数据位于 `.local/postgres/`，Python 环境仍使用根目录的 uv workspace。
默认业务数据库为 PostgreSQL，集成测试与浏览器测试使用独立测试库。
