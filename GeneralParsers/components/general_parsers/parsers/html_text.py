from __future__ import annotations

import re
import logging

import markdown
from bs4 import BeautifulSoup

from ..utils import decode_text, run_sync

logger = logging.getLogger(__name__)


async def parse_txt(file_bytes: bytes, filename: str) -> str:
    logger.info(f'Parsing TXT file: {filename}')
    return decode_text(file_bytes)


async def parse_md(file_bytes: bytes, filename: str) -> str:
    logger.info(f'Parsing Markdown file: {filename}')

    def _sync():
        md_content = file_bytes.decode('utf-8', errors='ignore')
        html_content = markdown.markdown(
            md_content, extensions=['extra', 'codehilite', 'tables', 'toc', 'fenced_code']
        )
        soup = BeautifulSoup(html_content, 'html.parser')
        text_parts = []
        for element in soup.children:
            if element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                level = int(element.name[1])
                text_parts.append('#' * level + ' ' + element.get_text().strip())
            elif element.name == 'p':
                text = element.get_text().strip()
                if text:
                    text_parts.append(text)
            elif element.name in ['ul', 'ol']:
                for li in element.find_all('li'):
                    text_parts.append(f'* {li.get_text().strip()}')
            elif element.name == 'pre':
                code_block = element.get_text().strip()
                if code_block:
                    text_parts.append(f'```\n{code_block}\n```')
            elif element.name == 'table':
                table_str = _extract_table(element)
                if table_str:
                    text_parts.append(table_str)
            elif element.name:
                text = element.get_text(separator=' ', strip=True)
                if text:
                    text_parts.append(text)
        return re.sub(r'\n\s*\n', '\n\n', '\n'.join(text_parts)).strip()

    return await run_sync(_sync)


async def parse_html(file_bytes: bytes, filename: str) -> str:
    logger.info(f'Parsing HTML file: {filename}')

    def _sync():
        html_content = file_bytes.decode('utf-8', errors='ignore')
        soup = BeautifulSoup(html_content, 'html.parser')
        for s in soup(['script', 'style']):
            s.decompose()
        text_parts = []
        container = soup.body if soup.body else soup
        for element in container.children:
            if element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                level = int(element.name[1])
                text_parts.append('#' * level + ' ' + element.get_text().strip())
            elif element.name == 'p':
                text = element.get_text().strip()
                if text:
                    text_parts.append(text)
            elif element.name in ['ul', 'ol']:
                for li in element.find_all('li'):
                    text = li.get_text().strip()
                    if text:
                        text_parts.append(f'* {text}')
            elif element.name == 'table':
                table_str = _extract_table(element)
                if table_str:
                    text_parts.append(table_str)
            elif element.name:
                text = element.get_text(separator=' ', strip=True)
                if text:
                    text_parts.append(text)
        return re.sub(r'\n\s*\n', '\n\n', '\n'.join(text_parts)).strip()

    return await run_sync(_sync)


def _extract_table(table_element) -> str:
    """Convert a BeautifulSoup table element into a Markdown table string."""
    headers = [th.get_text().strip() for th in table_element.find_all('th')]
    rows = []
    for tr in table_element.find_all('tr'):
        cells = [td.get_text().strip() for td in tr.find_all('td')]
        if cells:
            rows.append(cells)

    if not headers and not rows:
        return ''

    lines = []
    if headers:
        lines.append(' | '.join(headers))
        lines.append(' | '.join(['---'] * len(headers)))

    for row_cells in rows:
        padded = row_cells + [''] * (len(headers) - len(row_cells)) if headers else row_cells
        lines.append(' | '.join(padded))

    return '\n'.join(lines)
