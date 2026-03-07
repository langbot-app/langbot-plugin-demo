# GeneralParsers

Official LangBot parser plugin that extracts structured text from files for KnowledgeEngine plugins (e.g. LangRAG).

## Supported Formats

| Format | MIME Type | Parser |
|--------|-----------|--------|
| PDF | `application/pdf` | PyPDF2 page text extraction |
| DOCX | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | python-docx paragraph extraction |
| Markdown | `text/markdown` | Convert to HTML, then structured extraction (headings, lists, code blocks, tables) |
| HTML | `text/html` | BeautifulSoup extraction (auto-removes script/style) |
| TXT | `text/plain` | Auto encoding detection (chardet) |

## Architecture

```
┌──────────────────────────────────────────────┐
│  KnowledgeEngine Plugin (e.g. LangRAG)       │
│  Chunk → Embedding → Store → Retrieve        │
└──────────────────┬───────────────────────────┘
                   │ invoke_parser (RPC)
┌──────────────────▼───────────────────────────┐
│          GeneralParsers                      │
│                                              │
│  File bytes → Format detection → Parse       │
│                                              │
│  ParseResult:                                │
│    ├── text: Full extracted text              │
│    ├── sections: Heading-split sections       │
│    │   └── TextSection(content, heading,      │
│    │                   level)                 │
│    └── metadata: filename, MIME type, etc.    │
└──────────────────────────────────────────────┘
```

## Features

- **Section Structure Recognition** - Detects Markdown-style headings (`# ~ ######`) and splits into leveled sections
- **Table to Markdown** - Tables in HTML/Markdown are converted to Markdown table format
- **Async Parsing** - File parsing runs in a thread pool to avoid blocking the event loop
- **Auto Encoding Detection** - Uses chardet for encoding detection, supports GBK, UTF-8, etc.
- **Format Fallback** - Unsupported formats are automatically tried as plain text

## Usage

1. Install this plugin in LangBot
2. When uploading files to a knowledge base, select GeneralParsers as the parser
3. Parse results are automatically passed to the KnowledgeEngine plugin for further processing

## Development

```bash
pip install -r requirements.txt
cp .env.example .env
```

Configure `DEBUG_RUNTIME_WS_URL` and `PLUGIN_DEBUG_KEY` in `.env`, then launch with your IDE debugger.
