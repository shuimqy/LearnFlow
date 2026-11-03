# 模型配置

用户可从侧栏“账号设置”分别配置账号的 LLM 和 Embedding，账号下所有课程共用。
支持百炼、硅基流动、DeepSeek LLM 和 OpenAI 兼容接口、固定样本连接测试及服务端加密凭据。
LLM 同时用于问答、修改建议与课件识别；更换 Embedding 会先建立新索引，完成后统一切换。
详细字段、能力要求、索引规则和主密钥备份见 [账号设置](account-settings.md)。
下文命令行配置用于服务端系统默认模型，未自定义的账号沿用默认值。

DeepSeek 可在账号设置选择 `deepseek-flash` 或 `deepseek-v4-pro` 并填写自己的 Key。
Flash 支持图片，Pro 仅文本；JSON Object 与思考参数已适配。
系统默认也可在 `.env` 设置 `LLM_PROVIDER=deepseek`、`LLM_BASE_URL=https://api.deepseek.com`、
`LLM_MODEL=deepseek-flash`、`LLM_API_KEY` 及 `LLM_ENABLE_THINKING=true/false`。
DeepSeek 默认配置会使用 JSON Object，Pro 自动关闭图片能力；Embedding 另行配置。
文档依据：[思考模式](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/)、
[JSON 输出](https://api-docs.deepseek.com/zh-cn/guides/json_mode/)、
[图片输入](https://api-docs.deepseek.com/zh-cn/guides/vision/)。
尚未使用真实 DeepSeek Key 测试，账号内“测试连接”可发送固定样本验证。

硅基流动的 `deepseek-ai/DeepSeek-V4-Flash` 已按网页连接测试的固定提示实测：JSON Object 返回 `status=ok`、`answer=LearnFlow OK`，164 个输入 Token、11 个输出 Token。
实测未读取用户课件，提供的 Key 仅用于请求鉴权，没有写入脚本或日志。视觉识别与嵌入模型需另行测试。

当前已接入阿里云百炼的两个模型：

| 用途 | 模型 | 已验证能力 |
| --- | --- | --- |
| 文本向量 | `qwen3.7-text-embedding` | 1024 维向量、pgvector 读写及余弦查询 |
| 文本生成 | `qwen3.8-flash` | 普通回复、原生 JSON Schema 结构化输出 |

接口说明见 [Embedding 文档](https://help.aliyun.com/zh/model-studio/embedding-interfaces-compatible-with-openai/)、
[qwen3.8-flash 文档](https://help.aliyun.com/zh/model-studio/qwen3-8-flash)和
[结构化输出文档](https://help.aliyun.com/zh/model-studio/qwen-structured-output)。

本机已使用提供的 API Key 实测：4 条中文测试文本返回 4 条 1024 维向量，
共 115 个输入 Token；返回向量成功写入 PostgreSQL 临时表并完成余弦相似度查询。
线性代数查询把相关内容排在烘焙内容前面。这是连接与基本检索方向检查，不代表真实课件效果评估。

LLM 的两次真实请求均成功：普通回复返回 `LearnFlow LLM OK`，结构化请求返回符合 Schema 的线性无关解释。
两次共使用 91 个输入 Token、41 个输出 Token。默认关闭思考模式。

## 导入凭据

导入百炼控制台导出的名称/值格式 CSV，读取其中的 `apiKey` 和 `openAiCompatible`。
使用 CSV 给出的业务空间专属接口地址，不自行猜测地域。

```powershell
uv run --all-packages python -m app.cli.models configure-embedding --credentials-csv "C:\path\credentials.csv" --model qwen3.7-text-embedding --dimensions 1024
```

LLM 可复用已配置的 Embedding 凭据：

```powershell
uv run --all-packages python -m app.cli.models configure-llm --model qwen3.8-flash
```

也可为 `configure-llm` 添加 `--credentials-csv "C:\path\credentials.csv"`，导入另一组凭据。
两种模型分别保存配置，之后更换某一方的密钥不会自动修改另一方。

上述命令将系统凭据写入本机被 Git 忽略的 `.env`。原 CSV 不修改，既有数据库连接配置保留。
配置命令不会输出密钥；CSV 导入只接受阿里云官方 HTTPS 地址。账号设置可另外填写兼容接口，
用户凭据在数据库中加密保存。所有模型请求均不跟随重定向。

| 配置 | 说明 |
| --- | --- |
| `EMBEDDING_API_KEY` | CSV 中的 API Key，在设置对象中使用 `SecretStr` |
| `EMBEDDING_BASE_URL` | CSV 中的兼容接口地址，包含 `/compatible-mode/v1` |
| `EMBEDDING_MODEL` | 当前为 `qwen3.7-text-embedding` |
| `EMBEDDING_DIMENSIONS` | 当前为 `1024` |
| `EMBEDDING_BATCH_SIZE` | 每次最多 20 条；客户端会拆分更大的输入列表 |
| `EMBEDDING_TIMEOUT_SECONDS` | 请求超时，默认 30 秒 |
| `EMBEDDING_AUTO_INDEX` | 默认 `true`，知识保存成功后及提问时补交后台索引 |
| `RAG_MIN_SIMILARITY` | 语义检索最低余弦相似度，默认 `0.45` |
| `CHAT_MAX_TOKENS` | 问答输出上限，默认 `4096` |
| `LLM_API_KEY` | LLM 的 API Key，使用 `SecretStr` |
| `LLM_BASE_URL` | LLM 的兼容接口地址，包含 `/compatible-mode/v1` |
| `LLM_MODEL` | 当前为 `qwen3.8-flash` |
| `LLM_ENABLE_THINKING` | 默认 `false` |
| `LLM_MAX_TOKENS` | 默认输出上限 2048；请求使用 `max_completion_tokens`，调用方可按任务调整 |
| `LLM_TIMEOUT_SECONDS` | 请求超时，默认 60 秒 |

## 查看和验证

查看本地配置状态，不调用模型：

```powershell
uv run --all-packages python -m app.cli.models status
```

执行真实模型请求并验证 pgvector：

```powershell
uv run --all-packages python -m app.cli.models check-embedding
```

这条命令会向模型发送 4 句固定测试文本，并显示模型、维度、Token 用量和检索排序。
不发送用户课件，不输出完整向量或密钥。数据库验证使用临时表，提交后自动删除，不创建业务账户和知识点。

验证 LLM 普通回复和 JSON Schema 输出：

```powershell
uv run --all-packages python -m app.cli.models check-llm
```

这条命令会发送两次固定测试请求，显示回复、结构化结果和 Token 用量。验证命令会产生模型调用费用。
LLM 客户端通过 Pydantic 校验结构化结果，拒绝截断或不完整的回复，不将思考内容作为回答返回。

自动化测试通过 `httpx.MockTransport` 检查请求格式、批次拆分、返回顺序、异常向量、超时、
JSON Schema 校验、截断处理、错误脱敏和凭据导入，不调用真实模型。

## 当前范围

已完成模型请求客户端、本地凭据配置、真实 API 验证和 pgvector 读写验证。
已接入知识点后台向量生成、模型与维度跟踪、当前版本校验，以及课程问答的语义与关键词混合检索。
知识库列表搜索仍按文本关键词查找，问答流程、补建命令与配置见 [课程问答](chat.md)。

真实固定文本的 RAG 链路可通过 `uv run --all-packages python -m app.cli.rag_probe` 验证。
本机已跑通 Embedding → pgvector → LLM → 引用校验，数学问题命中相关文本，相似度为 0.7099。
这次测试使用 102 个向量输入 Token、441 个 LLM 输入 Token 和 234 个输出 Token，不涉及用户课件。

`qwen3.8-flash` 已用于逐页图像识别、知识点、公式、例题及习题提取，结果自动入库，并保留来源与识别提示。
真实图像输入与 Windows Redis / RQ 流程已经用固定测试页面验证。详见 [课件提取](extraction.md)。
同一模型也用于修改建议审查和课程问答。
