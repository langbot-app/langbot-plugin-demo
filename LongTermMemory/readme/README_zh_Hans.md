# LongTermMemory

LangBot 长期记忆插件，采用双层记忆设计：

- L1 核心画像：注入到 system prompt
- L2 情景记忆：通过 KnowledgeEngine 检索并注入

## 作用

- 提供 `remember` 工具，用于写入情景记忆
- 提供 `recall_memory` 工具，用于主动检索情景记忆并使用受控过滤条件
- 提供 `update_profile` 工具，用于更新稳定画像信息
- 通过 EventListener 自动注入画像和当前说话人身份
- 通过 KnowledgeEngine 在模型调用前检索相关情景记忆
- 提供 `!memory` 命令用于查看和调试记忆状态

## 设计说明

本插件尽量复用 LangBot 现有的扩展点，而不是依赖额外的核心补丁：

- L1 画像存储在插件存储中，格式为 JSON
- L2 情景记忆存储在向量数据库中
- 通过将本插件的 KnowledgeEngine 绑定到 pipeline，实现按 pipeline 显式启用
- 当前实现假设每个插件实例只维护一个 memory KB，并通过 metadata 做隔离

当前实现是围绕现有 LangBot 和 SDK API 设计的。后续如果 LangBot 提供更明确的 memory API、session 身份 API 或 KB 注册 API，插件可以进一步简化，但现有架构本身不需要因此推翻。

## 为什么暂时不向 Agent 开放元数据过滤

虽然底层运行时支持 metadata filter，但本插件目前没有在 Agent 流中直接暴露任意原始元数据过滤能力。

原因包括：

- 不同知识引擎和向量后端没有统一的 metadata schema
- 过滤字段名、值格式、支持的操作符可能各不相同
- Agent 当前没有稳定的 schema 来源，难以正确构造过滤条件

如果未来 LangBot 能为每个知识库提供统一的可过滤元数据字段描述，就可以再考虑开放更通用的 Agent 侧 metadata filter。

不过，由于长期记忆插件自己的 memory schema 是稳定的，本插件已经提供了受控的 `recall_memory` 工具入口，支持按说话人、时间范围等固定参数主动检索记忆，而不是让大模型直接拼接底层 raw filter。

## 隔离模型

支持两种隔离模式：

- `session`：每个群聊或私聊各自独立
- `bot`：同一个 bot 下的所有会话共享记忆

在当前部署模型下，这通常已经足够，因为插件实例一般会绑定在特定的 LangBot 运行环境或 bot 上。

## 使用方法

1. 安装并启用本插件。
2. 使用本插件的 KnowledgeEngine 创建一个 memory knowledge base。
3. 配置以下参数：
   - `embedding_model_uuid`
   - `isolation`
   - 可选 `max_results`
4. 让 Agent 使用：
   - `remember` 记录事件、计划、情景事实
   - `recall_memory` 在自动召回不足时主动检索记忆
   - `update_profile` 记录稳定偏好和画像信息
5. 使用 `!memory`、`!memory profile`、`!memory search <query>` 查看记忆状态。

## 组件

- KnowledgeEngine: [`memory_engine.py`](/home/yhh/workspace/langbot-plugin-memory/components/knowledge_engine/memory_engine.py)
- EventListener: [`memory_injector.py`](/home/yhh/workspace/langbot-plugin-memory/components/event_listener/memory_injector.py)
- Tools: [`remember.py`](/home/yhh/workspace/langbot-plugin-memory/components/tools/remember.py), [`recall_memory.py`](/home/yhh/workspace/langbot-plugin-memory/components/tools/recall_memory.py), [`update_profile.py`](/home/yhh/workspace/langbot-plugin-memory/components/tools/update_profile.py)
- Command: [`memory.py`](/home/yhh/workspace/langbot-plugin-memory/components/commands/memory.py)

## 目前还缺什么

和 `langbot-plugin-demo` 里的插件相比，这个插件之前主要缺的是用户可读文档：

- 根目录 `README.md`
- `readme/` 下的多语言说明

其余核心文件基本齐全，包括 manifest、图标、tool YAML、command YAML 和 KnowledgeEngine schema。
