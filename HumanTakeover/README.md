# HumanTakeover

[简体中文](readme/README_zh_Hans.md) | [日本語](readme/README_ja_JP.md)

A human-takeover & manual-reply plugin for LangBot. It lets a human operator take over any private or group conversation through a built-in Web console, block the AI from responding, and reply manually with text, images, or files.

## Features

- **Block AI on takeover**: When a conversation is taken over, the AI pipeline is stopped (`prevent_default`).
- **Web console (single Page component)**: Two-column layout with a collapsible info panel, following the LangBot design language and dark/light themes.
- **All conversations**: Lists every private chat and group chat; group messages distinguish individual senders.
- **Manual reply**: Send plain text, images (base64), and files (base64) from the console.
- **10-minute auto-release**: If there is no human response within the configured timeout, the takeover is released automatically. A live countdown is shown during human silence.
- **Trigger words**: When a user message contains a configured trigger word, the conversation is flagged as unhandled (WeChat-style red dot on the avatar), an alert toast is shown, and (optionally) the conversation is auto-taken-over.
- **Profile cards**: Click a user/group avatar to view available info (ID, group, bot, adapter).
- **Persistence**: Conversations and messages are stored via LangBot `plugin_storage` (database-backed) and survive restarts.
- **Clear storage**: One-click button (with a custom confirm dialog) to wipe all stored data.
- **i18n**: Full Simplified Chinese / English interface.

## Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `takeover_timeout` | integer | 600 | Auto-release takeover if no human response within this many seconds. |
| `trigger_words` | array[string] | `[]` | Messages containing any of these words flag the session as unhandled and auto take over. |
| `auto_takeover_on_trigger` | boolean | true | Whether to automatically take over when a trigger word is matched. |

## Usage

1. Install and enable the plugin in LangBot, configure the fields above.
2. Open the **Human Takeover** page from the WebUI sidebar.
3. Select a conversation, click **Take Over** to block the AI, then reply manually.
4. Click the avatar to inspect user/group info; use **Clear Storage** to reset data.

## Components

- **EventListener**: records messages, caches the adapter, matches trigger words, and blocks the AI while taken over.
- **Page (`console`)**: the Web management console (`index.html` + `console.py`).
