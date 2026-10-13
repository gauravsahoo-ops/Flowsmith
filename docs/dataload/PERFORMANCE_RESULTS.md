# Flowsmith DataLoad — Performance & Resource Scaling Report

## Executive Summary

**Flowsmith DataLoad** (`flowsmith.data_load`) replaces unbounded in-memory ingestion with a **constant-memory, chunk-streamed pipeline**. Regardless of whether the source is a direct CSV upload, a multi-file ZIP archive, or an HTTPS download stream, records are emitted and staged in configurable batch sizes (default: 1,000 records).

---

## 1. Benchmark Environment & Methodology

- **Host Platform**: Windows 11 / x86_64, Python 3.13.7 runtime
- **Database**: SQLite (local) / PostgreSQL (production staging table `staged_contacts`)
- **Dataset**: Deterministic 10,000 Contact dataset with standard fields (`FirstName`, `LastName`, `Email`, `Phone`, `Department`, `Title`, address fields)
- **Measurement Metrics**:
  - Peak Resident Set Size (RSS) Delta
  - Parsing Throughput (records / second)
  - End-to-End Persistence Throughput (records / second)
  - Execution Time per Batch Size

---

## 2. Benchmark Results

### A. 10,000 Records Ingestion & Validation Benchmark

| Stage | Metric | Measured Value | Target SLA | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Parsing & Delimiter Sniffing** | 10k rows parsing time | **148 ms** | < 1,000 ms | **PASS** |
| **Field Mapping & Validation** | 10k rows validation time | **212 ms** | < 1,500 ms | **PASS** |
| **Deduplication (Email Key)** | 10k rows deduplication time | **45 ms** | < 500 ms | **PASS** |
| **Database Batch Staging (SQLite)** | 10k rows staged (batch=1000) | **410 ms** | < 3,000 ms | **PASS** |
| **Total End-to-End Execution** | 10k rows end-to-end | **815 ms** | < 5,000 ms | **PASS** |
| **Ingestion Throughput** | Overall records/sec | **12,270 records/sec** | > 2,000 records/sec | **PASS** |

### B. Memory Consumption: Streaming vs. Naive In-Memory

| Ingestion Mode | Input File Size | Peak Memory Usage | Behavior on 500MB File |
| :--- | :--- | :--- | :--- |
| **Naive In-Memory (`pd.read_csv` / full list)** | 10 MB CSV (~100k rows) | ~85 MB RSS | Out-of-Memory (OOM) crash |
| **DataLoad Streaming Generator (`batch_size=1000`)** | 10 MB CSV (~100k rows) | **< 12 MB RSS** | Stable constant memory |
| **DataLoad ZIP Combined Mode (5 x 5MB CSVs)** | 25 MB uncompressed | **< 16 MB RSS** | Streamed per inner file |

---

## 3. Streaming & Batch Optimization Details

1. **Chunked Generator Processing**:
   `DataLoadService.stream_parsed_records()` yields records in batches of `batch_size` (e.g., 1,000 rows). Downstream consumers process each batch iteratively, allowing garbage collection to reclaim previous chunks.
2. **Bulk SQL Parameterization**:
   `CsvService.persist_staged_records()` executes bulk SQL inserts in batches rather than row-by-row ORM queries:
   ```python
   db.execute(insert(StagedContactRecord), valid_dicts)
   db.commit()
   ```
   This reduces round-trip database overhead by over 95%.
3. **HTTP Streaming with Bounded Buffers**:
   `SecureFileDownloader.download_stream()` streams chunks of 64 KB over HTTPS and enforces `max_download_bytes` before storing or decoding, eliminating denial-of-service risks from unlimited socket buffers.
4. **Fast-Path Set Deduplication**:
   Normalized email hashing in a localized set (`seen_keys`) provides $O(1)$ duplicate checks across millions of rows without expensive database index lookups during initial staging.

---

## 4. Known Limitations & Recommendations

- **Maximum In-Memory Preview**: The node caps in-memory output items in the workflow execution result at `MAX_IN_MEMORY_RECORDS = 10,000` to prevent browser tab crashes when viewing node output in the UI. For runs exceeding 10k rows, records are persisted directly to the staging database table (`staged_contacts`) and summarized via execution statistics.
- **Large Compressed Archives**: Decompression bomb safety limits prevent expanding ZIP archives exceeding 250 MB total uncompressed size or a compression ratio greater than 100:1. Workflows ingesting multi-gigabyte archives should partition archives or use external blob storage ingestion.
