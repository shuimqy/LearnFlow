# 课程包格式 v1

## 在网页中使用

1. 在课程详情点击「导出课程包」，下载 ZIP。
2. 在接收端打开「我的课程 → 导入课程」，选择 ZIP。
3. 校验通过后会新建一门课程。PDF、章节、知识点、原题和题图可以直接打开。导入会重建文本索引，向量可通过接收端的 Embedding 配置生成。

可以先用发布页附带的《离散数学》试一次。[下载课程包](https://github.com/shuimqy/LearnFlow/releases/download/v0.2.0/learnflow-discrete-mathematics-v1.zip)

## ZIP 内容

课程包是一个 ZIP，入口文件 `manifest.json` 记录 `format=learnflow.course`、`format_version=1`、课程名称、说明和颜色。`files` 列出其余成员的路径、字节长度和 SHA-256。JSON 和 JSONL 使用 UTF-8。

| 成员                       | 数据及引用                                                                                                             |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `documents.json`           | PDF 的包内 ID、文件名、文件路径、物理页数和题目模式                                                                    |
| `chapters.json`            | 所属 PDF、标题、顺序和包含起止页的章节范围                                                                             |
| `pages.jsonl`              | 已完成的转录页，按 PDF ID 和物理页码定位                                                                               |
| `knowledge.jsonl`          | 知识点与题目的当前正文、摘要和来源。来源含 PDF ID、文件名、物理页码及引文，文件失效时保留引文并将 PDF ID 记为 `null`。 |
| `exercises.jsonl`          | 已入库的原题记录，按 `example.kind` 区分习题和例题。题目关联 PDF 页与知识点 ID，保留原题、已有答案和解题内容。         |
| `embedding.json`           | 切块规则、文本拼接格式、导出时的 Embedding 模型元数据及预留索引列表                                                    |
| `chunks.jsonl`             | 每块的知识点 ID、从 0 开始的块序号和 UTF-8 文本 SHA-256                                                                |
| `files/documents/<id>.pdf` | 原始 PDF                                                                                                               |
| `files/assets/<id>.png`    | 题图和原题裁片。题目记录保留裁切角色、顺序、页码、归一化坐标、核对状态以及图片路径。                                   |

包内 ID 用来连接课程中的记录，导入时会分配新的 ID。题目的 `knowledge_id` 对应 `knowledge.jsonl` 中的正文，因此原题和后来修订的正文都能保存。裁片坐标以页面左上角为原点，PDF 物理页码从 1 开始。

`embedding.json` 记录切块配置，以及导出端的模型提供商、模型名称、版本、维度和指纹。接口地址和密钥由接收端配置。v1 的 `indexes` 为 `[]`，`chunks.jsonl` 记录文本哈希，用于将来校验向量与文本块的对应关系。

## 命令行

导出和校验会检查文件哈希、PDF 页数、记录关联和文本块哈希。

```powershell
uv run --all-packages python -m app.cli.course_package export --course-id <course-id> .local/course-packages/course.zip
uv run --all-packages python -m app.cli.course_package verify .local/course-packages/course.zip
```

多用户模式导出时指定 `--owner-id`。格式定义位于 `backend/app/schemas/course_package.py`。
