# LangRAG

LangBot RAG（检索增强生成）引擎插件。由官方开发的默认 RAG 引擎，使用在 LangBot 内部配置的向量数据库、Embedding 模型创建和检索知识库。

## 功能特性

- **外部 Parser 集成** - 优先使用 GeneralParsers 这类 Parser 插件提供的预解析结果，包括结构化 sections 和文档 metadata
- **内置解析兜底** - 当未配置外部 Parser 时，仍可回退到内置解析器
- **多种索引策略** - 平面分块、父子分块、LLM 生成的问答对
- **灵活检索方式** - 向量检索、全文检索或混合检索
- **查询改写** - HyDE、Multi-Query、Step-Back 策略以提升召回率
- **可配置分块** - 递归字符分割，支持自定义分块大小和重叠长度
- **结构化分块** - 当 parser 提供 sections 时，会尽量保留标题层级、页码和表格边界
- **上下文扩展** - 可为每个命中 chunk 追加相邻 chunk，提升返回上下文完整性
- **文档管理** - 按文档删除已索引的向量

## 架构

```
┌─────────────────────────────────┐
│         LangBot Core            │
│  (Embedding / VDB / Storage)    │
└──────────┬──────────────────────┘
           │ RPC (IPC)
┌──────────▼──────────────────────┐
│          LangRAG                │
│  ┌───────────────────────────┐  │
│  │       知识引擎             │  │
│  │  解析 → 分块 → 嵌入       │  │
│  │      → 存储 / 检索        │  │
│  └───────────────────────────┘  │
└─────────────────────────────────┘
```

## 摄入流程

LangRAG 现在优先使用 LangBot Host 提供的 parser 结果：

1. LangBot 读取上传文件
2. GeneralParsers 这类 Parser 插件先提取 `text`、`sections` 和 `metadata`
3. LangRAG 直接消费这些结构化结果
4. 如果没有 parser 输出，再回退到 LangRAG 内置解析器
5. 按当前索引策略构建 chunks 或 Q&A 对
6. 由 LangBot Host 生成 embedding 并写入向量库

因此，LangRAG 与外部 Parser 插件搭配使用时效果通常更好。

## 配置

### 知识库创建

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `embedding_model_uuid` | 嵌入模型 | 必填 |
| `index_type` | 索引策略：`chunk`、`parent_child` 或 `qa` | `chunk` |
| `chunk_size` | 每个分块的字符数 | 512 |
| `overlap` | 分块之间的重叠字符数 | 50 |
| `parent_chunk_size` | 父分块大小（仅 parent_child 模式） | 2048 |
| `child_chunk_size` | 子分块大小（仅 parent_child 模式） | 256 |
| `qa_llm_model_uuid` | 用于生成问答对的 LLM（仅 qa 模式） | - |
| `questions_per_chunk` | 每个分块生成的问题数（仅 qa 模式） | 1 |

### 检索

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `top_k` | 返回的结果数量 | 5 |
| `search_type` | 检索模式：`vector`、`full_text` 或 `hybrid` | `vector` |
| `query_rewrite` | 改写策略：`off`、`hyde`、`multi_query` 或 `step_back` | `off` |
| `rewrite_llm_model_uuid` | 用于查询改写的 LLM（启用改写时） | - |
| `context_window` | 为每个命中结果追加的相邻 chunk 数量 | 0 |

## 索引策略

- **chunk** - 默认平面分块。将文档分割为固定大小的分块，直接对每个分块进行嵌入；如果 parser 提供了 sections，则会优先按 section 边界分块。
- **parent_child** - 两级分块。先分割为大的父分块，再分割为小的子分块。对子分块进行嵌入，但返回父分块文本以提供更丰富的上下文；有 sections 时会优先把 section 当作天然父块边界。
- **qa** - LLM 生成的问答对。将文本分块后，使用 LLM 为每个分块生成问答对，并对问题进行嵌入；如果有 sections，问答生成也会按 section 进行。

## 查询改写

- **hyde** - 假设性文档嵌入。为查询生成一个假设性回答，然后对该回答进行嵌入用于检索。
- **multi_query** - 生成 3 个查询变体，分别检索后按分数合并结果。
- **step_back** - 生成一个更抽象的问题，同时使用原始查询和抽象查询进行检索。

## 与 GeneralParsers 配合使用

当前更推荐将 LangRAG 与 GeneralParsers 搭配使用，因为后者可以提供：

- 更干净的 PDF 文本提取
- 结构化 sections
- 保留表格结构的文本
- 文档级 metadata
- 可选的视觉模型 OCR 和图片描述

LangRAG 在摄入时会直接消费这些 parser 输出，通常能得到比内置 fallback parser 更好的分块质量和检索效果。

## 开发

```bash
pip install -r requirements.txt
cp .env.example .env
```

在 `.env` 中配置 `DEBUG_RUNTIME_WS_URL` 和 `PLUGIN_DEBUG_KEY`，然后使用 IDE 调试器启动。

## 链接

- [LangBot 文档](https://docs.langbot.app/)
