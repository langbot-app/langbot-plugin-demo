# AgenticRAG

AgenticRAG 将当前 pipeline 已配置的知识库暴露为一个可供 Agent 调用的工具，使 Agent 可以先查看可用知识库，再按需检索相关内容。

## 作用

- 提供一个工具：`query_knowledge`
- 支持两个动作：
  - `list`：列出当前 pipeline 可见的知识库
  - `query`：从一个或多个指定知识库中检索相关文档片段
- 以 JSON 形式返回结果，便于 Agent 继续分析、总结和回答

## 实现机制

本插件本身并不实现新的 RAG 引擎，而是对 LangBot 已有的按 `query_id` 作用域隔离的知识库能力做了一层工具封装：

- `list_pipeline_knowledge_bases()`：列出当前 query 所属 pipeline 可访问的知识库
- `retrieve_knowledge()`：对一个或多个指定知识库执行检索，返回合并后的 top-k 条结果

工具被调用时，运行时会自动注入当前会话对应的 `query_id`。插件内部通过 `QueryBasedAPIProxy` 持有这个上下文，因此业务侧只需要传：

- `kb_id` 或 `kb_ids`
- `query_text`
- `top_k`

虽然底层运行时支持 metadata filters，但本插件目前没有在 Agent 流的工具调用中把原始元数据过滤能力直接暴露给大模型。原因是不同知识引擎和向量后端对 metadata 字段、字段类型、值格式和过滤语义的约定并不统一，而当前 Agent 侧也没有稳定的 schema 来源来正确构造这些过滤条件。

后续如果生态里能够为每个知识库提供更统一的可过滤字段与操作符描述方式，我们可以再考虑把 metadata filter 能力开放给 Agent 使用。

## 安全设计

本插件只允许访问当前 pipeline 配置过的知识库。

- LangBot 运行时也会再次校验 `kb_id` 是否属于当前 pipeline

因此，即使模型因为 prompt 注入尝试构造其他知识库 ID，也不应越权访问未授权的知识库。

## 使用方法

1. 安装并启用本插件。
2. 在当前 pipeline 的 local agent 配置中绑定一个或多个知识库。
3. 让 Agent 调用 `query_knowledge`：
   - 先使用 `action="list"` 查看可用知识库
   - 再使用 `action="query"`，单库检索时传入 `kb_id`，多库并行检索时传入 `kb_ids`
   - 同时传入 `query_text`，以及可选的 `top_k`（作用于合并后的结果集）

## 参数说明

当 `action="query"` 时，可用参数如下：

- `kb_id`：单库检索时的目标知识库 UUID
- `kb_ids`：多库并行检索时的目标知识库 UUID 数组
- `query_text`：检索查询文本
- `top_k`：可选，返回结果数量，必须为正整数，默认值为 `5`，作用于合并后的结果集

如果多库并行检索时部分知识库失败、部分成功，工具会返回一个包含 `results` 和 `failed_kbs` 的 JSON 对象，便于 Agent 继续使用部分成功结果。

## 典型调用流程

1. Agent 先列出当前可用知识库。
2. 根据知识库名称和描述选择一个或少量合适的 KB。
3. 使用明确、具体的查询语句执行检索。
4. 基于返回的片段内容继续回答问题或执行下一步推理。
