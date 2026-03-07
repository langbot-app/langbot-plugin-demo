# GeneralParsers

LangBot 官方通用文档解析器插件，将文件提取为结构化文本，供 KnowledgeEngine 插件（如 LangRAG）使用。

## 支持格式

| 格式 | MIME Type | 解析方式 |
|------|-----------|---------|
| PDF | `application/pdf` | PyPDF2 提取页面文本 |
| DOCX | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | python-docx 提取段落 |
| Markdown | `text/markdown` | 转 HTML 后结构化提取（标题、列表、代码块、表格） |
| HTML | `text/html` | BeautifulSoup 提取（自动移除 script/style） |
| TXT | `text/plain` | 自动编码检测（chardet） |

## 架构

```
┌──────────────────────────────────────────────┐
│      KnowledgeEngine 插件（如 LangRAG）        │
│      分块 → Embedding → 存储 → 检索            │
└──────────────────┬───────────────────────────┘
                   │ invoke_parser (RPC)
┌──────────────────▼───────────────────────────┐
│          GeneralParsers                      │
│                                              │
│  文件字节 → 格式识别 → 解析 → ParseResult       │
│                                              │
│  ParseResult:                                │
│    ├── text: 完整提取文本                      │
│    ├── sections: 按标题拆分的段落列表            │
│    │   └── TextSection(content, heading,      │
│    │                   level)                 │
│    └── metadata: 文件名、MIME 类型等            │
└──────────────────────────────────────────────┘
```

## 特性

- **段落结构识别** - 自动检测 Markdown 风格标题（`# ~ ######`），按标题拆分为带层级的 sections
- **表格转 Markdown** - HTML/Markdown 中的表格自动转换为 Markdown 表格格式
- **异步解析** - 文件解析在线程池中执行，不阻塞事件循环
- **编码自动检测** - 使用 chardet 检测文件编码，支持 GBK、UTF-8 等
- **格式回退** - 不支持的格式自动尝试作为纯文本解析

## 使用方式

1. 在 LangBot 中安装本插件
2. 上传文件到知识库时，选择 GeneralParsers 作为解析器
3. 解析结果自动传递给 KnowledgeEngine 插件进行后续处理

## 开发

```bash
pip install -r requirements.txt
cp .env.example .env
```

在 `.env` 中配置 `DEBUG_RUNTIME_WS_URL` 和 `PLUGIN_DEBUG_KEY`，然后用 IDE 调试器启动。
