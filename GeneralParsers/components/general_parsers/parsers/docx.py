from __future__ import annotations

import io
import re
import logging

from docx import Document

from ..utils import run_sync

logger = logging.getLogger(__name__)


async def parse_docx(file_bytes: bytes, filename: str) -> tuple[str, dict]:
    """Parse DOCX with table extraction, heading styles, list recognition,
    and document-flow-order output.

    Returns:
        A tuple of (text, extra_metadata).
    """
    logger.info(f'Parsing DOCX file: {filename}')

    def _sync():
        from docx.table import Table as DocxTable
        from docx.text.paragraph import Paragraph

        doc = Document(io.BytesIO(file_bytes))
        parts = []
        has_tables = False
        word_count = 0

        for block in doc.element.body:
            tag = block.tag

            if tag.endswith('}p'):
                para = Paragraph(block, doc)
                text = para.text.strip()
                if not text:
                    continue

                style_name = para.style.name if para.style else ''

                # Heading recognition: "Heading 1" through "Heading 6"
                heading_match = re.match(r'Heading\s*(\d+)', style_name, re.IGNORECASE)
                if heading_match:
                    level = min(int(heading_match.group(1)), 6)
                    parts.append('#' * level + ' ' + text)
                elif 'List' in style_name:
                    parts.append('* ' + text)
                else:
                    parts.append(text)

                word_count += len(text)

            elif tag.endswith('}tbl'):
                has_tables = True
                try:
                    table = DocxTable(block, doc)
                    md = _docx_table_to_markdown(table)
                    if md:
                        parts.append('\n' + md + '\n')
                except Exception as e:
                    logger.warning(f'Failed to extract DOCX table: {e}')

        full_text = '\n'.join(parts)
        extra_metadata = {
            'word_count': word_count,
            'has_tables': has_tables,
        }
        return full_text, extra_metadata

    return await run_sync(_sync)


def _docx_table_to_markdown(table) -> str:
    """Convert a python-docx Table object into a Markdown table string."""
    rows_data = []
    for row in table.rows:
        cells = [cell.text.strip() for cell in row.cells]
        rows_data.append(cells)

    if not rows_data:
        return ''

    # First row as header
    header = rows_data[0]
    col_count = len(header)
    lines = [
        '| ' + ' | '.join(header) + ' |',
        '| ' + ' | '.join(['---'] * col_count) + ' |',
    ]
    for row in rows_data[1:]:
        padded = row + [''] * (col_count - len(row)) if len(row) < col_count else row[:col_count]
        lines.append('| ' + ' | '.join(padded) + ' |')

    return '\n'.join(lines)
