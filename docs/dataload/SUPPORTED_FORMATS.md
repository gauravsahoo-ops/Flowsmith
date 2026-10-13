# Flowsmith DataLoad — Supported Formats Specification

## Overview

**Flowsmith DataLoad** (`flowsmith.data_load`) is an enterprise-grade file-ingestion node designed to import, download, extract, parse, validate, and transform tabular records for downstream workflow processing.

This document specifies the exact file formats currently implemented, verified, and supported in Flowsmith DataLoad, alongside their configuration parameters, constraints, and planned extensions.

---

## 1. Supported Input Modes

| Input Mode | Identifier | Description | Persistence Mechanism |
| :--- | :--- | :--- | :--- |
| **Upload File** | `upload` | User uploads file via local file picker or drag-and-drop. Also accepts data URLs or Base64 payloads. | Persisted via `POST /api/v1/files` to Flowsmith Object Store (`file_id`). Workflow graph stores reference only, avoiding bloated definition JSON. |
| **Download from URL** | `download` | Node retrieves remote file via HTTP or HTTPS stream during execution. Supports expressions (`{{ ... }}`). | Streamed securely to bounded memory/disk sandbox with strict SSRF controls and credentials integration. |

---

## 2. Implemented & Tested File Formats

In accordance with strict verification standards, only formats with direct automated unit and integration tests are listed as production-supported:

### A. Comma-Separated Values (`.csv`)
- **MIME Types**: `text/csv`, `application/csv`, `text/plain`
- **Magic Bytes / Sniffing**: Header heuristic, delimiter frequency detection
- **Encoding Support**: UTF-8, UTF-8 BOM (`\xef\xbb\xbf` auto-stripped), ASCII, Latin-1
- **Features**:
  - Quoted fields containing delimiters (e.g., `"New York, NY"`)
  - Escaped quotes (`""` RFC 4180 standard and configurable `\` escapes)
  - Embedded newlines within quoted fields
  - Configurable null-value representations (defaults: `""`, `null`, `NULL`, `None`, `NA`, `N/A`)
  - Configurable header-row presence (`has_header: true/false`)
  - Dynamic column mapping and schema validation (e.g. Salesforce Contact, Lead)

### B. Tab-Separated Values (`.tsv`)
- **MIME Types**: `text/tab-separated-values`, `text/tsv`, `text/plain`
- **Magic Bytes / Sniffing**: Tab delimiter detection (`\t`)
- **Encoding Support**: UTF-8, UTF-8 BOM, ASCII, Latin-1
- **Features**:
  - Same robust quoting and newline escaping as CSV
  - Automatic delimiter switching when `.tsv` extension or predominant tabs are detected

### C. ZIP Archives (`.zip`)
- **Magic Bytes**: `PK\x03\x04`, `PK\x05\x06`, `PK\x07\x08`
- **Supported Archive Payloads**:
  1. **Single Tabular File**: ZIP archive enclosing exactly one `.csv` or `.tsv` file.
  2. **Multiple Tabular Files (Combine Mode)**: Combines multiple `.csv` / `.tsv` files into a single unified record stream with header union or strict validation.
  3. **Multiple Tabular Files (Single Mode)**: Selects a specific inner file by name (`archive_inner_file`) or picks the first matching entry.
  4. **Nested Directories**: Automatically traverses folders (e.g., `2026/Q1/apac/sales.csv`) using glob filters (e.g., `**/*.csv`).
  5. **Mixed Content Archives**: Safely filters out unsupported files (e.g., images, PDFs, binaries, executables) while reporting non-fatal unsupported entries.
  6. **Nested ZIP Archives**: Supports archives within archives up to configurable depth (default: 2 levels, maximum 5 levels).
- **Metadata Enriched per Record**:
  - `_source_file`: The inner tabular filename (e.g., `sales.csv`).
  - `_archive_path`: The full path inside the archive hierarchy (e.g., `2026/Q1/apac/sales.csv`).
  - `_row_number`: 1-indexed source row number within that file.

### D. GZIP Compressed Files (`.gz`)
- **Magic Bytes**: `\x1f\x8b`
- **Supported Payloads**: Single compressed `.csv` or `.tsv` stream (e.g., `export.csv.gz`).
- **Features**: Transparent on-the-fly streaming decompression into the delimited parser.

---

## 3. Extensible Parser Registry Architecture

Flowsmith DataLoad is built around the `FormatRegistry` abstraction (`app.services.dataload.registry`):

```
                       ┌─────────────────────────┐
                       │     DataLoadService     │
                       └────────────┬────────────┘
                                    │
                                    ▼
                       ┌─────────────────────────┐
                       │     FormatRegistry      │
                       └────────────┬────────────┘
         ┌──────────────────────────┼──────────────────────────┐
         ▼                          ▼                          ▼
┌─────────────────┐        ┌─────────────────┐        ┌─────────────────┐
│ DelimitedFormat │        │ ZipArchiveFormat│        │   GzipFormat    │
│     Handler     │        │     Handler     │        │     Handler     │
│  (.csv, .tsv)   │        │     (.zip)      │        │     (.gz)       │
└─────────────────┘        └─────────────────┘        └─────────────────┘
         │                          │                          │
         └──────────────────────────┼──────────────────────────┘
                                    │
                                    ▼
                       ┌─────────────────────────┐
                       │ Record Streaming Engine │
                       │ (Constant Bounded RAM)  │
                       └─────────────────────────┘
```

Each format implements the `FormatHandler` interface:
```python
class FormatHandler(ABC):
    @abstractmethod
    def can_handle(self, filename: str, header_bytes: bytes) -> bool:
        ...

    @abstractmethod
    def parse_stream(
        self,
        raw_bytes: bytes,
        filename: str,
        options: DataLoadOptions,
        *,
        node_id: str = "data_load",
    ) -> Generator[list[dict[str, Any]], None, None]:
        ...
```

---

## 4. Planned Extensions (Roadmap)

The modular architecture permits future handlers without modifying existing parsing loops:

| Format | Target Handler | Planned Capabilities | Status |
| :--- | :--- | :--- | :--- |
| **JSON** | `JsonFormatHandler` | Array of objects, root selector path (`data.items[*]`) | Planned |
| **JSONL / NDJSON** | `NdjsonFormatHandler` | Line-delimited streaming JSON for high-throughput logs | Planned |
| **Excel (`.xlsx`)** | `ExcelFormatHandler` | Sheet selection, cell range slicing via openpyxl streaming | Planned |
| **XML** | `XmlFormatHandler` | XPath record element extraction | Planned |
| **Parquet** | `ParquetFormatHandler` | Columnar analytics files via pyarrow streaming | Planned |

> **Note**: These formats are explicitly tracked as planned extensions and will only be marked supported after comprehensive test suites and security sandboxing are implemented.
