from __future__ import annotations

from typing import Any

from langbot_plugin.api.definition.components.page import Page


class ManagerPage(Page):
    """FAQ Manager page — handles CRUD and search API calls."""

    async def handle_api(self, endpoint: str, method: str, body: Any = None) -> Any:
        plugin = self.plugin

        if endpoint == '/entries' and method == 'GET':
            return {'entries': plugin.entries}

        if endpoint == '/entries' and method == 'POST':
            question = (body or {}).get('question', '').strip()
            answer = (body or {}).get('answer', '').strip()
            if not question or not answer:
                return {'error': 'question and answer are required'}
            entry = plugin.add_entry(question, answer)
            await plugin.persist()
            return {'entry': entry}

        if endpoint == '/entries' and method == 'PUT':
            entry_id = (body or {}).get('id', '')
            entry = plugin.update_entry(
                entry_id,
                (body or {}).get('question'),
                (body or {}).get('answer'),
            )
            if entry is None:
                return {'error': 'entry not found'}
            await plugin.persist()
            return {'entry': entry}

        if endpoint == '/entries' and method == 'DELETE':
            entry_id = (body or {}).get('id', '')
            if plugin.delete_entry(entry_id):
                await plugin.persist()
                return {'deleted': entry_id}
            return {'error': 'entry not found'}

        if endpoint == '/search' and method == 'POST':
            query = (body or {}).get('query', '')
            return {'results': plugin.search(query)}

        return {'error': f'Unknown endpoint: {method} {endpoint}'}
