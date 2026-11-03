# 课程知识库

每门课对应一个逻辑知识库。底层共用 PostgreSQL / pgvector 的表，所有查询和写入都校验课程归属。
没有公开的跨课程检索入口，用户课件不会自动汇入公共知识库。当前实际运行 PostgreSQL 16.15 + pgvector 0.8.6。

## 当前可用流程

课程详情 → 课程知识库 → 添加知识点 → 选择课件及页码 → 读取原文 → 保存。

知识点也可以作为独立笔记保存。添加、编辑和提出修改建议时，正文支持 Markdown 与 KaTeX 实时预览，
桌面左右对照、手机上下显示；可隐藏预览以专心编辑。富文本编辑尚未接入。
上传 PDF 自动开始逐页识别，知识点、公式和原有题目直接存入课程知识库，保留来源和识别提示。
详见 [课件提取](extraction.md)。

## 数据组织

| 表 | 职责 |
| --- | --- |
| `document_pages` | 不可编辑的逐页提取结果、页码、解析器版本和文本哈希 |
| `source_fragments` | 原文片段、字符范围及是否排除原文检索 |
| `knowledge_points` | 当前知识正文、摘要、版本、状态及课程归属 |
| `knowledge_sources` | 当前知识与课件片段的关联，保留文件名、页码和引用文字 |
| `knowledge_revisions` | 每次确认操作后的完整快照、原因、操作人与版本号 |
| `knowledge_proposals` | 尚未生效的修改建议、基准版本与处理结果 |
| `knowledge_chunks` | 当前有效知识的派生检索文本、内容哈希和向量状态 |
| `knowledge_embeddings` | 账号自定义模型的向量，按配置与知识块隔离，重建期间允许两套并存 |
| `page_extractions` | 逐页识别状态、模型转录、提示和 Token 用量 |
| `extraction_drafts` | 知识点、例题与习题的结构化提取记录及入库关联 |

不额外创建与课程一一对应的知识库表，`course_id` 就是当前知识库边界。
来源页面按文档和物理页码缓存；不同用户或课程的相同资料目前仍独立保存。
跨用户解析缓存和 Embedding 缓存尚未实现，未来只能复用内部计算结果，不能扩大资料访问权限。

## 来源规则

- 页码以 PDF 的物理页为准，从 1 开始。使用 PyMuPDF 提取选定页并缓存，不改变原始文件。
- 引用必须来自当前课程的课件。填写引用文字时，校验它确实是该页原文的连续片段。
- 引用留空时保存整页文本。没有文本层的页面仍保留页码引用，视觉识别转录单独保存，不伪装成原始文本层。
- 知识正文允许补充解释，但不会据此改写原文。
- 删除课件会清理页面和片段，当前引用的文件链接置空，已保存的引用文字与修订快照保留。
- 编辑或恢复带有失效文件引用的旧知识时，保留原引用文字，不伪造可用文件链接。

## 修订与确认

创建时生成第 1 版。编辑、确认纠错、归档和恢复都生成新版本，记录操作原因与完整快照。
所有修改带上 `expected_version`，过期请求返回 409。数据库层还使用 SQLAlchemy 版本条件更新，
防止两个请求在同时读取旧版本后互相覆盖。

提出建议不会修改正文或检索内容。建议包含基准版本和拟修改快照，用户比较后可以采纳或拒绝。
知识已发生其他修订时，基于旧版本的待确认建议自动标为 `superseded`，不能直接采纳。
历史恢复会创建新版本，不会删除中间版本。

当前可在页面手动提出建议；后续对话纠错应调用同一组建议接口，再由用户确认。
确认交由模型处理后，`qwen3.8-flash` 会结合建议原因、正文和关联课件给出意见及完整修订。
页面同时显示模型意见与实际写入结果；依据不足、不采纳或版本已变更时不写入。
具体流程和来源边界见 [修改建议的模型处理](proposal-review.md)。
修改建议可单独删除，已保存的知识正文、修订和检索内容保留；正在被模型处理的建议需要等待处理结束。
桌面上的知识列表与详情各自滚动，切换知识点后详情回到顶部；窄屏下保留列表内滚动，详情按页面阅读。
课程问答已保存会话和消息，并检查课程与消息归属。对话中自动提出纠错建议尚未接入，
后续需验证建议引用的消息属于同一用户和课程。

## 检索同步

确认修订、保存修订记录和重建检索块放在同一数据库事务中。
事务失败时全部回滚。归档会移除检索块；检索同时检查课程、知识状态和当前版本，即使有遗留旧块也不会返回。
删除整门课时级联清理知识、修订、建议、来源和检索块。

当前文本块按字符切分，约 1200 字符一块、240 字符重叠，并附带标题和摘要。
知识库列表的关键词检索是文本包含匹配；课程问答另外使用语义与关键词混合检索。
列表每页最多 200 条，支持 `offset`；检索每次最多返回 50 个知识点。

目前只检索知识点正文派生的文本块，原文片段作为引用保存，不独立进入检索。
因此已确认纠正的正文不会同时被旧原文答案覆盖。后续接入原文检索时，必须处理 `excluded` 标记，
并将已确认的纠正随对应片段一起交给回答模型。

`embedding` 在 PostgreSQL 中使用 pgvector 的 `vector` 类型，在 SQLite 中使用 JSON 兼容测试。
新文本块的向量为空，状态为 `pending`，不会生成模拟向量。已选择 `qwen3.7-text-embedding`、1024 维，
完成真实接口验证，尚未创建 ANN 索引。

`store_embeddings()` 由后台 Worker 批量写回，会检查知识版本、状态、块数量和向量有效性；
过期任务不能覆盖当前版本。知识事务提交后自动入队，失败可补交；记录向量模型与维度，
配置身份不匹配的向量不会混入当前语义检索。问答只检索当前有效版本，并保存回答引用快照。
账号模型切换使用独立索引，重建完成后统一启用新配置，详见 [账号设置](account-settings.md)。
流程、限制与补建命令见 [课程问答](chat.md)，凭据配置见 [模型配置](models.md)。

## 接口

所有路径均位于 `/api` 下并要求登录。

| 方法与路径 | 功能 |
| --- | --- |
| `GET /courses/{course_id}/knowledge` | 列表，支持 `status`、`q`、`limit`、`offset` |
| `POST /courses/{course_id}/knowledge` | 创建知识点 |
| `GET /courses/{course_id}/knowledge/{id}` | 查看知识点 |
| `PATCH /courses/{course_id}/knowledge/{id}` | 保存修订，要求版本和修改原因 |
| `DELETE /courses/{course_id}/knowledge/{id}?expected_version=...` | 归档，保留历史 |
| `GET /courses/{course_id}/knowledge/{id}/revisions` | 查看完整修订记录 |
| `POST /courses/{course_id}/knowledge/{id}/restore` | 从指定修订恢复为新版本 |
| `GET/POST /courses/{course_id}/knowledge/{id}/proposals` | 查询或提出修改建议 |
| `POST /courses/{course_id}/knowledge/{id}/proposals/{proposal_id}/accept` | 模型审查并处理，返回意见与实际写入结果 |
| `POST /courses/{course_id}/knowledge/{id}/proposals/{proposal_id}/reject` | 拒绝建议 |
| `DELETE /courses/{course_id}/knowledge/{id}/proposals/{proposal_id}` | 删除建议记录及模型处理结果，保留已有知识修订 |
| `POST /courses/{course_id}/knowledge/search` | 当前课程的文本块检索，返回正文片段及来源 |
| `GET /courses/{course_id}/knowledge/stats` | 有效、归档、待确认建议和检索块数量 |
| `POST /documents/{document_id}/pages/{page_number}/extract` | 读取并缓存指定 PDF 页 |
| `PATCH /courses/{course_id}/source-fragments/{fragment_id}` | 标记原文片段的排除状态及原因 |

检索接口返回 `match_type: "text"`，统计接口返回 `search_mode: "text"`。
具体请求结构和字段长度见 FastAPI `/docs`。

## 迁移和验证

新增迁移 `0002` 只创建知识库相关表，不修改现有课程或文件记录。

```powershell
uv sync --locked --all-packages
uv run --all-packages alembic -c backend/alembic.ini upgrade head
uv run --all-packages pytest backend/tests -q
npm --prefix frontend run test:e2e
```

自动测试覆盖课程和用户隔离、引用校验、并发版本冲突、事务回滚、建议确认、归档恢复、
失效文件引用保留，以及旧检索内容和过期向量写回清理。
PostgreSQL / pgvector 的实际服务联调、向量写入和余弦距离查询已经通过集成测试。
Embedding API、自动索引服务、语义检索与课程问答已接入并通过自动测试。
真实链路已使用固定文本验证，真实课程的检索召回和问答效果仍需人工评估。
