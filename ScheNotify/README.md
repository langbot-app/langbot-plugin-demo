# ScheNotify

使用自然语言计划日程提醒 | Schedule notifications with natural language

## 功能介绍 Features

ScheNotify 是一个 LangBot 插件，允许用户通过自然语言与 LLM 交互来设置定时提醒。

ScheNotify is a LangBot plugin that allows users to set timed reminders through natural language interaction with LLM.

### 主要功能 Main Features

- 🤖 **自然语言交互**：通过 LLM 理解用户的日程安排意图
- ⏰ **智能时间解析**：自动获取当前时间并计算提醒时间
- 🌐 **多语言支持**：支持中文和英文的提醒消息
- 📝 **日程管理命令**：查看和删除已计划的提醒
- 🔔 **自动通知**：到达设定时间后自动发送提醒消息

---

- 🤖 **Natural Language Interaction**: Understand user's scheduling intentions through LLM
- ⏰ **Smart Time Parsing**: Automatically get current time and calculate reminder time
- 🌐 **Multi-language Support**: Support Chinese and English reminder messages
- 📝 **Schedule Management Commands**: View and delete scheduled reminders
- 🔔 **Automatic Notifications**: Automatically send reminder messages at scheduled time

## 配置 Configuration

### 语言设置 Language Setting

在插件配置中可以选择提醒消息的语言：

You can select the language for reminder messages in plugin configuration:

- `zh_Hans` (简体中文 / Simplified Chinese) - 默认 Default
- `en_US` (English / 英语)

## 使用方法 Usage

### 1. 通过 LLM 设置提醒 Schedule via LLM

直接用自然语言告诉 LLM 你的日程安排：

Simply tell the LLM your schedule in natural language:

**中文示例 Chinese Examples:**
```
明天下午3点提醒我开会
后天早上9点提醒我交报告
下周一中午12点提醒我吃饭
2024-12-25 18:00 提醒我圣诞晚餐
```

**English Examples:**
```
Remind me to have a meeting at 3 PM tomorrow
Remind me to submit the report at 9 AM the day after tomorrow
Remind me to have lunch at 12 PM next Monday
Remind me about Christmas dinner at 2024-12-25 18:00
```

LLM 会自动：
1. 调用 `get_current_time_str` 获取当前时间
2. 解析你的时间表达并转换为标准格式
3. 调用 `schedule_notify` 创建提醒

The LLM will automatically:
1. Call `get_current_time_str` to get current time
2. Parse your time expression and convert to standard format
3. Call `schedule_notify` to create reminder

### 2. 查看计划的提醒 View Scheduled Reminders

使用命令查看所有计划中的提醒：

Use command to view all scheduled reminders:

```
!sche
```

示例输出 Example output:
```
[Notify] 计划中的提醒：
#1 2024-12-25 18:00:00：圣诞晚餐
#2 2024-12-26 09:00:00：交报告
```

### 3. 删除提醒 Delete Reminder

使用命令删除指定的提醒（使用 `!sche` 查看的序号）：

Use command to delete a specific reminder (using the number from `!sche`):

```
!dsche i <序号>
```

示例 Example:
```
!dsche i 1   # 删除第1个提醒 Delete the 1st reminder
```

## 组件说明 Components

### Tools 工具

1. **get_current_time_str** - 获取当前时间
   - 返回格式：`YYYY-MM-DD HH:MM:SS`
   - LLM 在设置提醒前必须先调用此工具

2. **schedule_notify** - 计划通知
   - 参数：时间字符串、提醒内容
   - 自动从 session 参数获取会话信息发送提醒

### Commands 命令

1. **sche** (别名: s) - 列出所有计划的提醒
2. **dsche** (别名: d) - 删除指定的提醒

## 技术细节 Technical Details

- 定时检查间隔：每 60 秒
- 时间精度：分钟级（程序每分钟检查一次）
- 会话获取：通过 Tool 的 session 参数自动获取
- 持久化：当前使用内存存储（重启后丢失）

---

- Check interval: Every 60 seconds
- Time precision: Minute level (checks every minute)
- Session info: Automatically obtained through Tool's session parameter
- Persistence: Currently uses in-memory storage (lost on restart)

## 示例对话 Example Conversation

**用户 User:** 明天下午2点提醒我参加会议

**LLM:** 好的，我来为你设置提醒。

*[LLM 调用 get_current_time_str]*
*[LLM 调用 schedule_notify(time_str="2024-12-26 14:00:00", message="参加会议")]*

**LLM:** 已经为你设置好了！将在 2024-12-26 14:00:00 提醒您：参加会议

*[第二天下午2点]*

**机器人 Bot:** [Notify] 参加会议

## 注意事项 Notes

- 提醒时间必须是未来时间，过去的时间会被拒绝
- 提醒消息会发送到设置提醒时的同一个会话
- 重启插件后，未发送的提醒会丢失（未来版本将支持持久化）

---

- Reminder time must be in the future, past times will be rejected
- Reminder messages will be sent to the same session where the reminder was set
- Unsent reminders will be lost after plugin restart (persistence will be supported in future versions)

## 开发者信息 Developer Info

- 作者 Author: RockChinQ
- 版本 Version: 0.2.0
- 插件类型 Plugin Type: LangBot Plugin v1

## License

Part of the LangBot plugin ecosystem.