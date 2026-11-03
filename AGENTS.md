# 项目约定

- Python 环境与依赖统一使用 uv：`uv sync --all-packages`、`uv run`，提交 `uv.lock`。
- 默认业务数据库为 PostgreSQL + pgvector，不得静默回退 SQLite。本机原生运行环境由 `app.cli.database` 管理；Python 环境仍使用 uv。新库不迁移旧 SQLite 账户和课件。
- 开发环境为 Windows。不要使用 Celery；任务队列使用 Redis，执行器采用 RQ 的 `SpawnWorker`，不能依赖 `fork`。
- 网页按实际学习任务设计，排版克制，避免宣传页式大标题、装饰渐变、虚构统计和无功能按钮。不放口号、励志文案和无操作意义的介绍，只保留功能名称、操作说明和必要提示。
- 注释只解释必要的约束、原因和边界，不复述代码，不使用宣传式措辞。
- 用户资料按用户隔离。文件、课程、任务接口都要检查归属。
- 当前按阶段推进，未接入的解析、生成或问答能力要明确说明，不展示模拟成功状态。
- 后端按业务拆分 `api/`、`models/`、`schemas/`，可复用业务放 `services/`。前端 `app/` 保留路由入口，功能实现放 `features/`，公共界面放 `components/`。详见 `docs/architecture.md`。
- Windows 开发入口为根目录 `start.bat`、`stop.bat`，启动器使用 uv，不能按端口强制结束用户手动启动的服务。
- 知识点修订必须校验版本，并在同一事务中保存历史和替换检索块；修改建议确认后才生效。不得静默覆盖新版本或让旧内容继续被检索。
- 课程知识库共用存储，检索按用户和课程隔离。原文引用与知识正文分开保存。Embedding 未接入时保持空值和 pending 状态，不生成模拟向量。详见 `docs/knowledge-base.md`。
- 系统模型密钥放在本机忽略的 `.env`；账号自定义 API Key 在数据库中加密保存，加密主密钥由环境变量或 `.local/model-encryption.key` 管理。运行时使用 `SecretStr`，不要输出凭据或服务端可能回显密钥的错误正文。模型可用性检查使用固定测试文本，不自动上传用户课件。
