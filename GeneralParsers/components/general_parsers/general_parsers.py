from __future__ import annotations

import io
import re
import asyncio
import logging
from typing import Callable, Any

import base64

import fitz
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


class GeneralParsers(Parser):
    """GeneralParsers component that extracts structured text from binary files.

    Supports PDF, DOCX, Markdown, HTML, and plain text files.
    Based on the parsing logic from LangRAG.
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
        extra_metadata = {}
        if parser_method is None:
            logger.warning(f'Unsupported file format: {extension} for {filename}, trying as text')
            text = self._decode_text(file_bytes)
        else:
            try:
                result = await parser_method(file_bytes, filename)
                # PDF parser returns (text, extra_metadata), others return str
                if isinstance(result, tuple):
                    text, extra_metadata = result
                else:
                    text = result
            except Exception as e:
                logger.error(f'Failed to parse {extension} file {filename}: {e}')
                text = None

        if text is None:
            text = ''

        sections = self._split_sections(text, filename)

        metadata = {
            'filename': filename,
            'mime_type': context.mime_type,
            'extension': extension,
        }
        metadata.update(extra_metadata)

        return ParseResult(
            text=text,
            sections=sections,
            metadata=metadata,
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

    async def _parse_pdf(self, file_bytes: bytes, filename: str) -> tuple[str, dict]:
        """Parse PDF using PyMuPDF with table extraction, image extraction, and position-aware text.

        Returns:
            A tuple of (text, extra_metadata) where extra_metadata contains extracted images.
        """
        logger.info(f'Parsing PDF file: {filename}')

        def _sync():
            doc = fitz.open(stream=file_bytes, filetype='pdf')
            page_texts = []
            images = []

            for page_idx, page in enumerate(doc):
                page_num = page_idx + 1

                # --- Collect table regions to avoid duplicating table text ---
                tables = page.find_tables()
                table_rects = []
                table_entries = []  # (y0, markdown_str)
                for table in tables:
                    bbox = fitz.Rect(table.bbox)
                    table_rects.append(bbox)
                    md = _pymupdf_table_to_markdown(table)
                    if md:
                        table_entries.append((bbox.y0, md))

                # --- Extract text blocks with position info ---
                text_dict = page.get_text('dict', flags=fitz.TEXT_PRESERVE_WHITESPACE)
                text_entries = []  # (y0, text_str)
                for block in text_dict.get('blocks', []):
                    if block['type'] != 0:  # skip image blocks
                        continue
                    block_rect = fitz.Rect(block['bbox'])

                    # Skip text blocks that overlap significantly with a table region
                    in_table = False
                    for tr in table_rects:
                        overlap = block_rect & tr  # intersection
                        if not overlap.is_empty and overlap.height > block_rect.height * 0.5:
                            in_table = True
                            break
                    if in_table:
                        continue

                    lines_text = []
                    for line in block.get('lines', []):
                        spans_text = ''.join(span['text'] for span in line.get('spans', []))
                        stripped = spans_text.strip()
                        if stripped:
                            lines_text.append(stripped)
                    if lines_text:
                        text_entries.append((block['bbox'][1], '\n'.join(lines_text)))

                # --- Merge text and table entries by vertical position ---
                all_entries = []
                for y0, text in text_entries:
                    all_entries.append((y0, 'text', text))
                for y0, md in table_entries:
                    all_entries.append((y0, 'table', md))
                all_entries.sort(key=lambda e: e[0])

                page_parts = []
                for _, kind, content in all_entries:
                    if kind == 'table':
                        page_parts.append('\n' + content + '\n')
                    else:
                        page_parts.append(content)

                # --- Extract images ---
                for img_idx, img_info in enumerate(page.get_images(full=True)):
                    xref = img_info[0]
                    try:
                        pix = fitz.Pixmap(doc, xref)
                        # Convert CMYK / other color spaces to RGB
                        if pix.n - pix.alpha > 3:
                            pix = fitz.Pixmap(fitz.csRGB, pix)
                        img_bytes = pix.tobytes('png')
                        img_b64 = base64.b64encode(img_bytes).decode('ascii')
                        images.append({
                            'page': page_num,
                            'index': img_idx,
                            'width': pix.width,
                            'height': pix.height,
                            'base64': img_b64,
                        })
                        page_parts.append(f'[图片: 第{page_num}页-图片{img_idx + 1}]')
                    except Exception as e:
                        logger.warning(f'Failed to extract image xref={xref} on page {page_num}: {e}')

                if page_parts:
                    page_texts.append('\n'.join(page_parts))

            doc.close()

            full_text = '\n\n'.join(page_texts)
            extra_metadata = {}
            if images:
                extra_metadata['images'] = images
            return full_text, extra_metadata

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


def _pymupdf_table_to_markdown(table) -> str:
    """Convert a PyMuPDF Table object into a Markdown table string."""
    data = table.extract()
    if not data:
        return ''

    # Clean cell values: replace None with empty string, strip whitespace
    cleaned = []
    for row in data:
        cleaned.append([str(cell).strip() if cell is not None else '' for cell in row])

    if not cleaned:
        return ''

    # First row as header
    header = cleaned[0]
    lines = [
        '| ' + ' | '.join(header) + ' |',
        '| ' + ' | '.join(['---'] * len(header)) + ' |',
    ]
    for row in cleaned[1:]:
        # Pad or trim row to match header length
        padded = row + [''] * (len(header) - len(row)) if len(row) < len(header) else row[:len(header)]
        lines.append('| ' + ' | '.join(padded) + ' |')

    return '\n'.join(lines)
