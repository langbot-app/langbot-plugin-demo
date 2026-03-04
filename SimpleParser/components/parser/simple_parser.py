from __future__ import annotations

import io
import re
import asyncio
import logging
from typing import Callable, Any

import PyPDF2
from docx import Document
import chardet
import markdown
from bs4 import BeautifulSoup

from langbot_plugin.api.definition.components.parser.parser import Parser
from langbot_plugin.api.entities.builtin.rag.models import (
    ParseContext,
    ParseResult,
    TextSection,
)


logger = logging.getLogger(__name__)


class SimpleParser(Parser):
    """Parser component that extracts structured text from binary files.

    Supports PDF, DOCX, Markdown, HTML, and plain text files.
    Based on the parsing logic from SimpleRAGEngine.
    """

    async def parse(self, context: ParseContext) -> ParseResult:
        """Parse a file and extract structured text.

        Args:
            context: Contains file_content (bytes), mime_type, filename, and metadata.

        Returns:
            ParseResult with extracted text and optional structured sections.
        """
        filename = context.filename
        file_bytes = context.file_content

        # Determine extension from filename
        if '.' in filename:
            extension = filename.rsplit('.', 1)[-1].lower()
        else:
            extension = ''

        parser_method = getattr(self, f'_parse_{extension}', None)
        if parser_method is None:
            logger.warning(f'Unsupported file format: {extension} for {filename}, trying as text')
            text = self._decode_text(file_bytes)
        else:
            try:
                text = await parser_method(file_bytes, filename)
            except Exception as e:
                logger.error(f'Failed to parse {extension} file {filename}: {e}')
                text = None

        if text is None:
            text = ''

        sections = self._split_sections(text, filename)

        return ParseResult(
            text=text,
            sections=sections,
            metadata={
                'filename': filename,
                'mime_type': context.mime_type,
                'extension': extension,
            },
        )

    # ========== Section Extraction ==========

    @staticmethod
    def _split_sections(text: str, filename: str) -> list[TextSection]:
        """Split text into sections based on heading patterns."""
        if not text:
            return []

        # Try to split by markdown-style headings
        heading_pattern = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
        matches = list(heading_pattern.finditer(text))

        if not matches:
            # No headings found, return single section
            return [
                TextSection(
                    content=text,
                    heading=filename,
                    level=0,
                )
            ]

        sections = []
        for i, match in enumerate(matches):
            level = len(match.group(1))
            heading = match.group(2).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[start:end].strip()
            if content:
                sections.append(
                    TextSection(
                        content=content,
                        heading=heading,
                        level=level,
                    )
                )

        # Include text before first heading if any
        preamble = text[: matches[0].start()].strip()
        if preamble:
            sections.insert(
                0,
                TextSection(
                    content=preamble,
                    heading=filename,
                    level=0,
                ),
            )

        return sections

    # ========== Helpers ==========

    @staticmethod
    async def _run_sync(sync_func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Run a synchronous function in a thread to avoid blocking the event loop."""
        return await asyncio.to_thread(sync_func, *args, **kwargs)

    @staticmethod
    def _decode_text(file_bytes: bytes) -> str:
        """Decode bytes to text with encoding detection."""
        detected = chardet.detect(file_bytes)
        encoding = detected['encoding'] or 'utf-8'
        return file_bytes.decode(encoding, errors='ignore')

    # ========== Format-Specific Parsers ==========

    async def _parse_txt(self, file_bytes: bytes, filename: str) -> str:
        logger.info(f'Parsing TXT file: {filename}')
        return self._decode_text(file_bytes)

    async def _parse_pdf(self, file_bytes: bytes, filename: str) -> str:
        logger.info(f'Parsing PDF file: {filename}')

        def _sync():
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
            text_content = []
            for page in pdf_reader.pages:
                text = page.extract_text()
                if text:
                    text_content.append(text)
            return '\n'.join(text_content)

        return await self._run_sync(_sync)

    async def _parse_docx(self, file_bytes: bytes, filename: str) -> str:
        logger.info(f'Parsing DOCX file: {filename}')

        def _sync():
            doc = Document(io.BytesIO(file_bytes))
            text_content = [p.text for p in doc.paragraphs if p.text.strip()]
            return '\n'.join(text_content)

        return await self._run_sync(_sync)

    async def _parse_doc(self, file_bytes: bytes, filename: str) -> str:
        raise NotImplementedError('Direct .doc parsing not supported. Please convert to .docx first.')

    async def _parse_md(self, file_bytes: bytes, filename: str) -> str:
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

        return await self._run_sync(_sync)

    async def _parse_html(self, file_bytes: bytes, filename: str) -> str:
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

        return await self._run_sync(_sync)


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
