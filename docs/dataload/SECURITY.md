# Flowsmith DataLoad — Security & Threat Mitigation Specification

## Executive Summary

**Flowsmith DataLoad** (`flowsmith.data_load`) enforces strict enterprise defense-in-depth principles across all file-ingestion stages. Because file ingestion handles untrusted external inputs—both uploaded files and remote network URLs—the engine implements non-bypassable safeguards against Server-Side Request Forgery (SSRF), ZipSlip path traversals, decompression bombs, symlink attacks, and secret leakage.

---

## 1. Network & SSRF Defense Architecture

### Prohibited Target Networks
Flowsmith DataLoad rejects any network destination resolving to private, local, multicast, or cloud metadata endpoints:

- **Loopback Addresses**: `127.0.0.0/8`, `::1` (blocked in production; configurable in dev)
- **RFC 1918 Private Subnets**:
  - `10.0.0.0/8`
  - `172.16.0.0/12`
  - `192.168.0.0/16`
- **Link-Local Addresses**: `169.254.0.0/16`, `fe80::/10`
- **AWS / GCP / Azure Cloud Metadata**: `169.254.169.254`, `metadata.google.internal`, `instance-data`
- **Carrier-Grade NAT & Testnets**: `100.64.0.0/10`, `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`
- **Broadcast & Multicast**: `224.0.0.0/4`, `255.255.255.255`

### Pre-Flight DNS Resolution & Anti-Rebinding
Standard HTTP clients (like `curl` or `requests` with standard redirect following) are vulnerable to DNS rebinding and open redirect bypasses. DataLoad mitigates this via `validate_download_url`:

1. **Scheme Enforcement**: Only `https://` (and `http://` in dev) schemes are permitted. Schemes like `file://`, `ftp://`, `gopher://`, `data:`, `expect://` are immediately rejected.
2. **Synchronous DNS Lookup**: Resolves all IPv4 and IPv6 addresses associated with the hostname before initiating any TCP handshake.
3. **Subnet Membership Check**: If any resolved IP belongs to a forbidden subnet, the request is aborted with `SSRF_PROHIBITED_IP`.
4. **Step-by-Step Redirect Validation**:
   - `SecureFileDownloader` disables client-side automatic redirects (`follow_redirects=False`).
   - Each HTTP 3xx response is intercepted in a manual loop (up to `MAX_REDIRECTS = 5`).
   - The `Location` header is resolved against the previous URI and passed through the complete `validate_download_url` check before any secondary socket is opened.
   - An external server attempting to redirect to `http://169.254.169.254/latest/meta-data` or `http://192.168.1.1` is blocked with an explicit SSRF security violation.

### Download Constraints
- **Maximum Download Size**: Enforced via streaming byte counter (`max_download_bytes`, default 50 MB, configurable up to 500 MB). If the remote server exceeds this limit, the connection is instantly severed.
- **Connection & Read Timeouts**: Enforced per socket read (`timeout_seconds`, default 30s).
- **Sensitive URL & Secret Redaction**: Query string tokens (`token`, `access_token`, `key`, `api_key`, `secret`, `signature`, `password`) and basic auth credentials (`https://user:pass@...`) are automatically redacted with `[REDACTED]` prior to logging or reporting errors.

---

## 2. Archive Security & Zip Exploitation Defenses

Untrusted ZIP files present multiple vector classes: ZipSlip (path traversal), symlink dereferencing, and decompression bombs (ZIP bombs).

### A. Path Traversal & ZipSlip Prevention
- Every entry's filename inside a ZIP archive is inspected before decompression.
- Entries containing `..`, absolute paths (leading `/` or `\\`), drive letters (e.g., `C:\windows\system32`), or null bytes (`\x00`) are flagged as malicious.
- During any extraction, the target path is resolved using `os.path.abspath` and verified against the temporary sandbox directory:
  ```python
  if not resolved_path.startswith(sandbox_dir):
      raise NodeExecutionError("ZipSlip path traversal attempt detected", code="ZIP_SLIP_ATTEMPT")
  ```

### B. Symlink & Hardlink Rejection
- Entry permissions and attributes (`ZipInfo.external_attr`) are inspected.
- Entries with POSIX symlink bits (`S_IFLNK = 0o120000`) or Windows directory junctions are rejected. Extracted files are never linked outside the sandbox.

### C. Decompression Bomb & Resource Exhaustion Protection
ZIP archives can achieve compression ratios exceeding 1,000:1 (e.g. `42.zip`). The `ZipSecurityValidator` enforces hard limits:

| Parameter | Safety Threshold | Behavior on Breach |
| :--- | :--- | :--- |
| **Max Uncompressed Size** | 250 MB (`MAX_TOTAL_UNCOMPRESSED_BYTES`) | Aborts extraction with `ZIP_BOMB_DETECTED` |
| **Max Compression Ratio** | 100:1 (`MAX_COMPRESSION_RATIO`) | Aborts extraction if uncompressed size exceeds 5 MB and ratio > 100:1 |
| **Max Archive Entries** | 500 entries (`MAX_ARCHIVE_ENTRIES`) | Prevents inode exhaustion / processing locks |
| **Max Nesting Depth** | 2 levels (configurable up to 5) | Rejects recursive ZIP archives beyond configured limit |
| **Executable Rejection** | Executable extensions (`.exe`, `.bat`, `.cmd`, `.sh`, `.dll`, `.so`) | Extracted files are never executed; non-tabular files are filtered |

---

## 3. Sandboxing & Temporary File Lifecycle

All transient extractions occur within a dedicated, isolated temporary sandbox managed by `safe_temp_sandbox`:

```python
with safe_temp_sandbox(prefix="dataload_") as sandbox_dir:
    # All extractions, streaming reads, and conversions occur here
    ...
# Sandbox and all inner files are guaranteed deleted via shutil.rmtree in finally block
```

### Guarantees:
1. **Deterministic Cleanup**: The sandbox is completely purged on normal completion, execution error, timeout, or workflow cancellation.
2. **Access Isolation**: Sandboxes use OS-restricted permissions (`0o700` on POSIX systems).
3. **No Execution**: Sandboxed files are opened strictly in binary read mode (`rb`) and are never granted execute bits or spawned as subprocesses.

---

## 4. Downstream Data Isolation & Auditability

1. **Tenant Workspace Scoping**: All object store files (`file_id`) are scoped to the executing user's workspace and verified before reading.
2. **Auditable Metadata**: Ingested records retain origin tracking (`_source_file`, `_archive_path`, `_row_number`) without exposing server filesystem layout or backend storage tokens.
3. **Idempotent Executions**: Unique run IDs prevent double-ingestion into destination databases during retries.
