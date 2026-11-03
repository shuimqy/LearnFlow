# 课件知识与例题提取

上传 PDF → Redis / RQ 后台逐页识别 → 自动存入课程知识库。
完成后直接打开知识库；处理页面仅显示进度、失败原因和重试入口，不再要求逐条确认。
已有课件可在课程详情点击“提取知识与例题”开始处理，不会自动重新处理历史上传文件。

## 公式识别

PyMuPDF 提取文本层并渲染页面图；`qwen3.8-flash` 同时接收两者，使用图片识别分式、上下标、
根号、矩阵等排版。模型返回 JSON Schema，后端通过 Pydantic 校验。模型的图片输入能力见
[官方模型说明](https://help.aliyun.com/zh/model-studio/qwen3-8-flash)，图像请求格式见
[视觉理解接口](https://help.aliyun.com/zh/model-studio/vision)。

公式保存为 LaTeX，知识库使用 KaTeX 显示，来源链接可打开原始 PDF 对应页。
识别不清的公式标记为不确定；提示词要求不猜测缺失符号。识别疑点与页面提示保留在知识正文的“识别提示”中，
不阻止自动入库。之后可直接编辑知识点，或通过修改建议纠错。
KaTeX 能显示公式只表示语法可渲染，不证明数学内容或符号识别正确。

扫描页通过页面图片识别；原始文本层仍为空，不把模型转录内容伪装成 PDF 原文。
原始 PDF、文本层、模型转录和知识正文分别保存。扫描页的引用保留文件与物理页码，原文引用文字可为空。

## 例题与习题

同一请求同时返回知识点和原有题目，不额外调用模型解题。
题目区分 `worked_example`（讲解例题）和 `exercise`（留给学生的习题），保留：

- 题目名称、题干、选项及可辨认的图表文字。
- 课件明确提供的答案、解题步骤及公式；没有的字段留空。
- 本页来源、不完整或无法辨认的内容提示。

未给出的答案显示“课件未提供答案”。例题与习题自动以独立条目存入课程知识库，
正文按题干、课件答案和课件解题步骤组织，保留修订记录与来源。
结构化原始识别结果仍保留在内部提取记录中。当前没有独立题库、自动补解或 AI 出题功能。
上传时保存的习题偏好留给后续生成流程使用，不影响原有例题的识别。

## 保存与重试

`page_extractions` 保存每页状态、模型转录、可读性提示和 Token 用量；
`extraction_drafts` 表保留结构化提取结果与入库关联，名称沿用原实现。
每页的识别结果、知识正文、修订、引用与检索块在同一事务写入，任一步失败则该页全部回滚。

每次任务有独立运行标识。重复提交排队中的任务不会重复入队，过期任务不能写回新一轮处理。
每页单独提交，单页失败不丢弃其它页面；重试只处理未完成页面，不覆盖已入库或已编辑的知识点。
同一页面完全相同的知识记录去重；同课程下标题和正文相同的条目关联已有知识，不重复创建，也不恢复已归档条目。
尚不做语义去重或跨页合并，重复出现的额外页码保留在内部提取记录中。
文件被删除后，未完成任务不会重新建立文件或草稿。

旧版尚未入库的结果可直接补入，不需要再次调用模型；已入库、已编辑和已忽略的记录保持原状态：

```powershell
uv run --all-packages python -m app.cli.extraction pending
uv run --all-packages python -m app.cli.extraction import-existing --document-id <文档ID>
```

## 配置与运行

`start.bat` 会检查 Redis 并启动 Worker。Windows 默认使用项目目录内的便携
[Redis 社区构建](https://github.com/redis-windows/redis-windows/releases/tag/8.10.3)，下载时核对 SHA-256；
运行文件与 AOF 数据位于 `.local/redis/`。若 `REDIS_URL` 已可连接，则复用该服务。
Worker 基于 RQ SpawnWorker；本项目补充 Windows 子进程启动、等待与结束方式，避免依赖 `fork`、`wait4` 和 Unix 进程组。

单独运行时：

```powershell
uv run --all-packages python -m app.cli.queue setup
uv run --all-packages python -m app.cli.queue serve
# 另开终端
uv run --all-packages python -m app.workers.main
```

```powershell
uv run --all-packages python -m app.cli.queue status
```

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `EXTRACTION_AUTO_START` | `true` | 新上传文件保存后自动入队；关闭后可以手动开始 |
| `EXTRACTION_MAX_PAGES` | `300` | 单次页数上限，超限文件仍保存，需要拆分后处理 |
| `EXTRACTION_MAX_TOKENS` | `8192` | 每页响应上限，截断的结果拒绝保存，可重试 |

模型使用 `LLM_*` 配置，默认关闭思考模式。单页图像长边最多 2000 像素，文本层最多发送前 24000 字符，
文本被截断时显示提示。每页单独调用模型，上传自动识别会产生模型费用。
队列不可用时文件仍保存，处理记录显示错误并提供重试入口。

## 验证与限制

后端和浏览器测试使用模拟模型响应，不调用真实 API。
下列命令会使用固定生成的公式与题目页面，通过独立临时队列进行真实模型验证，不读取用户课件：

```powershell
uv run --all-packages python -m app.cli.extraction_probe
```

已验证真实 Redis + Windows SpawnWorker + `qwen3.8-flash` 图像请求，
测试页面中的分式、上下标、例题以及没有答案的习题均通过检查。
这只验证连接及固定样例，真实课件仍需核对。

正文提取仍按单页进行；跨页题干和推导尚未自动合并。提取结束后默认向 RQ 提交章节、题型、难度与原题区域整理任务，
可在[课件做题本](workbooks.md)查看、修正章节范围和核对裁片，跨页裁片可手动追加。
复杂图表、低清扫描、手写公式和密集排版仍可能有遗漏。
知识库已接入 Markdown 与公式预览、向量后台索引、混合检索和 RAG 问答，详见[课程问答](chat.md)。
