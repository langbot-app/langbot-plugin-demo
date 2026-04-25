from __future__ import annotations

from typing import Any

from langbot_plugin.api.definition.components.page import Page


class DashboardPage(Page):
    """FAQ Dashboard — read-only stats overview."""

    async def handle_api(self, endpoint: str, method: str, body: Any = None) -> Any:
        plugin = self.plugin

        if endpoint == '/stats':
            entries = plugin.entries
            total = len(entries)
            avg_len = 0
            if total > 0:
                avg_len = sum(len(e['answer']) for e in entries) // total
            return {
                'total_entries': total,
                'avg_answer_length': avg_len,
            }

        return {'error': f'Unknown endpoint: {method} {endpoint}'}
