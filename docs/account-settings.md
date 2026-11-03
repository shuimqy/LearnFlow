# 账号设置

入口为侧栏“账号设置”、左下角的账号名称，或 `/settings`。
可修改称呼，分别保存一套 LLM 和一套 Embedding。账号下所有课程共用模型配置，课程数据仍分别检索。
未自定义的用途沿用服务端 `.env` 默认配置，不修改其他账号的设置。

## 模型连接

LLM 和 Embedding 支持阿里云百炼、硅基流动及 OpenAI 兼容接口，LLM 另支持 DeepSeek。填写基础地址、模型名称和 API Key；
基础地址不包含 `/chat/completions` 或 `/embeddings`。远程接口使用 HTTPS，本机接口可使用
`http://localhost`、`http://127.0.0.1` 或 `http://[::1]`，请求不跟随重定向。

LLM 用于问答、修改建议和课件识别：

- 结构化输出可选原生 JSON Schema 或 JSON Object；两者都在服务端校验字段和引用。
- 百炼使用 `max_completion_tokens` 与思考模式参数；通用兼容接口使用 `max_tokens`。
- 未启用图片识别时，课件识别会显示明确错误，修改建议处理只核对来源文本。
- 接口协议兼容不代表每个模型都支持上述能力，应先测试连接。

DeepSeek 选择后会填入 `https://api.deepseek.com`，也接受官方 `/v1` 地址。
使用 OpenAI 格式的 Chat Completions，不能填 Anthropic 地址。
提供 `deepseek-flash`（支持图片）和 `deepseek-v4-pro`（仅文本）两个预设；
Pro 无法进行课件页面识别或发送聊天图片，已有文字问答和修改建议仍可用。
结构化输出固定为 JSON Object，由本地 Pydantic 继续校验，不向接口发送 JSON Schema 格式参数。

百炼和 DeepSeek 可按账号保存思考模式。DeepSeek 预设默认开启，以
`thinking.type=enabled/disabled` 发送；百炼仍使用 `enable_thinking`。
思考计入输出额度并可能增加响应时间；返回的 `reasoning_content` 不保存为聊天正文。
DeepSeek 思考模式下，意图判断上限为 4096 Token，普通模式为 768；连接测试分别为 4096 和 256。
其余任务沿用现有输出上限，复杂任务出现截断时可以关闭思考或调整服务端额度。
DeepSeek 仅接入 LLM，不可作为 Embedding 提供商，切换 LLM 不重建课程向量。
接口适配已用固定响应测试；使用自己的 DeepSeek Key 后点击“测试连接”验证真实可用性。

Embedding 需要填写实际输出维度。不接受 `dimensions` 参数的固定维度接口可取消该选项；
服务端仍严格校验返回维度。可填写服务商的模型版本，以区分同名模型更新。

硅基流动选项自动填入 `https://api.siliconflow.cn/v1`，使用自己的硅基流动 API Key。
LLM 预填 `deepseek-ai/DeepSeek-V4-Flash`，默认仅文本、JSON Object、关闭思考；模型名可改为控制台提供的完整名称。
识别课件或聊天图片需换为支持视觉的模型并启用图片识别。JSON Schema、JSON Object 和思考开关应按具体模型能力设置。
请求使用 `max_tokens`、`enable_thinking`，不使用 DeepSeek 官方接口的 `thinking.type`。
JSON Object 模式将结构约束与业务指令合并为一条 system 消息，并明确要求返回符合结构的数据对象，避免模型直接回传 JSON Schema。
Embedding 预填 `Qwen/Qwen3-Embedding-8B`、1024 维，发送 `dimensions`；切换到预设 BGE-M3 或 BGE 中文模型时，自动使用 1024 维并关闭该参数。
其他模型的维度以服务商说明和固定样本连接测试为准。更换服务商不会复用旧服务的密钥，也不会自动改动已有账号配置。
接口依据：[Chat Completions](https://api-docs.siliconflow.cn/docs/api/chat-completions-post)、[Embeddings](https://api-docs.siliconflow.cn/docs/api/embeddings-post)。

“测试连接”使用未保存的表单内容：Embedding 发送两句固定数学文本；LLM 检查固定 JSON 回复，
启用视觉时另提供写有固定英文的图片。测试不读取课件，不保存配置，可能产生调用费用。
通过仅说明接口和基本能力可用，不代表真实课程的识别或检索质量。

## 保存和索引切换

更换 LLM 立即对后续请求生效，不重建向量。已经开始的请求使用启动时读取的配置。
更换相同接口的 API Key 不重建向量。密钥留空表示保留原值；改变接口地址或类型后必须重新填写，
防止把旧服务的凭据发送到新地址。本机无认证接口可以明确选择不使用密钥。

更换 Embedding 的提供商、地址、模型、版本、维度或编码参数时：

1. 保存账号的新配置，保持当前模型和索引可用。
2. 通过 Redis / RQ 对所有课程的当前有效知识建立新索引。
3. 全部就绪后，在同一事务中切换账号配置，并清理旧配置与旧向量。

重建期间，新修改的知识会进入新索引，旧索引缺少的内容通过关键词补查。
失败可在设置页重试，也可取消本次切换。取消会清理待启用的索引，保留当前模型。
任务只保存配置编号和知识版本，不携带明文密钥；取消、替换或修订后，旧结果不能写回有效索引。
所有课程在完成后共同切换，不存在单门课程选用不同模型的入口。

索引重建会将知识文本发送到设置的 Embedding 接口，问答会发送问题和检索到的知识，
课件识别会发送页面图片。知识正文、生成的向量和检索数据库仍保存在本地 PostgreSQL。
保存按钮旁已说明数据用途与调用费用。

## 凭据和数据表

账号 API Key 用 Fernet 加密后存入 `model_profiles`，密文同时绑定用户 ID。
接口仅返回 `has_api_key`，不返回密钥明文或密文；运行时通过 `SecretStr` 传入模型客户端。
模型错误正文不会直接回传给网页。

主密钥可由 `MODEL_ENCRYPTION_KEY` 设置；留空时，首次保存自动生成
`.local/model-encryption.key`。该文件和 `.env` 都被 Git 忽略。
备份和迁移数据库时必须一并保留主密钥；丢失后只能让用户重新填写 API Key。
不要在已有加密记录时直接更换主密钥。

| 表 | 职责 |
| --- | --- |
| `account_models` | 每账号唯一，指向当前 LLM、当前 Embedding 与待启用 Embedding，保存设置版本 |
| `model_profiles` | 模型配置、配置指纹及加密凭据；重建完成或取消后清理不再使用的配置 |
| `knowledge_embeddings` | 按知识块和配置编号保存向量，允许重建期间两套索引并存 |

配置指纹包含提供商、基础地址、模型、版本、维度、参数及文本组织版本，排除 API Key。
原有系统默认向量增加指纹字段；来源配置未知的旧向量不被当作兼容向量复用。
旧课程、账号、课件和知识正文均保留。

## 接口与验证

迁移 `0006` 新增账号配置和并行索引表，启动脚本会执行迁移。

| 方法与路径（均在 `/api` 下） | 用途 |
| --- | --- |
| `PATCH /account/profile` | 修改称呼 |
| `GET /account/models` | 读取脱敏模型配置及账号索引进度 |
| `PUT /account/models/{kind}` | 保存配置，`kind` 为 `llm` 或 `embedding`，要求 `expected_version` |
| `POST /account/models/{kind}/test` | 用固定样本测试表单中的配置 |
| `POST /account/models/embedding/rebuild` | 补建或重试当前待处理索引 |
| `DELETE /account/models/embedding/pending?expected_version=...` | 取消待启用模型，校验设置版本 |

自动测试覆盖账号隔离、凭据加密、密钥保留、模型能力与协议、全账号索引切换、失败、取消、
过期任务和知识修订。浏览器测试使用隔离数据库及固定模型响应，检查实际表单与手机布局。
