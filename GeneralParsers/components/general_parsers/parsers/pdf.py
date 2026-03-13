from __future__ import annotations

import base64
import logging

import fitz

from ..utils import run_sync

logger = logging.getLogger(__name__)


async def parse_pdf(file_bytes: bytes, filename: str) -> tuple[str, dict]:
    """Parse PDF using PyMuPDF with table extraction, image extraction, and position-aware text.

    Returns:
        A tuple of (text, extra_metadata) where extra_metadata contains extracted images.
    """
    logger.info(f'Parsing PDF file: {filename}')

    def _sync():
        doc = fitz.open(stream=file_bytes, filetype='pdf')
        page_count = len(doc)
        page_texts = []
        images = []
        scanned_pages = []
        total_word_count = 0
        has_tables = False

        for page_idx, page in enumerate(doc):
            page_num = page_idx + 1

            # --- Collect table regions to avoid duplicating table text ---
            tables = page.find_tables()
            if tables:
                has_tables = True
            table_rects = []
            table_entries = []  # (y0, x0, markdown_str)
            for table in tables:
                bbox = fitz.Rect(table.bbox)
                table_rects.append(bbox)
                md = _pymupdf_table_to_markdown(table)
                if md:
                    table_entries.append((bbox.y0, bbox.x0, md))

            # --- Extract text blocks with position info ---
            text_dict = page.get_text('dict', flags=fitz.TEXT_PRESERVE_WHITESPACE)
            text_entries = []  # (y0, x0, text_str)
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
                    text_entries.append((block['bbox'][1], block['bbox'][0], '\n'.join(lines_text)))

            # --- Merge text and table entries by vertical position ---
            all_entries = []
            for y0, x0, text in text_entries:
                all_entries.append((y0, x0, 'text', text))
            for y0, x0, md in table_entries:
                all_entries.append((y0, x0, 'table', md))
            all_entries.sort(key=lambda e: (e[0], e[1]))

            page_parts = []
            for _, _, kind, content in all_entries:
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

            # --- Detect scanned pages and count words ---
            plain_text = page.get_text('text').strip()
            total_word_count += len(plain_text)
            page_has_images = len(page.get_images(full=True)) > 0
            if len(plain_text) < 30 and page_has_images:
                scanned_pages.append(page_num)

            if page_parts:
                page_texts.append(f'<!-- PAGE:{page_num} -->\n' + '\n'.join(page_parts))

        doc.close()

        full_text = '\n\n'.join(page_texts)
        extra_metadata = {
            'page_count': page_count,
            'word_count': total_word_count,
            'has_tables': has_tables,
            'has_scanned_pages': bool(scanned_pages),
        }
        if scanned_pages:
            extra_metadata['scanned_pages'] = scanned_pages
        if images:
            extra_metadata['images'] = images
        return full_text, extra_metadata

    return await run_sync(_sync)


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
