# Flowsmith Logs & Monitoring API Reference

This document provides a comprehensive REST API specification for Flowsmith's Execution Logs, Telemetry Inspection, Retry Engine, and Monitoring Metrics endpoints.

---

## 1. Authentication & Tenant Scoping

All endpoints require a valid Bearer token in the `Authorization` header:
```http
Authorization: Bearer <access_token>
```
Endpoints automatically enforce multi-tenant isolation. Users can only query executions associated with workflows they own, share, or belong to within their active organization and workspace. Attempting to query an execution belonging to another tenant returns `404 Not Found` to prevent identity enumeration.

---

## 2. Execution Logs & Query Endpoints

### 2.1 List & Filter Execution Logs
`GET /api/executions`

Returns a paginated list of execution records with multi-attribute filtering, sorting, and full-text search.

**Query Parameters:**
| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `page` | `int` | `1` | Page number (1-indexed) |
| `pageSize` | `int` | `20` | Items per page (max: `100`) |
| `workflow_id` | `string` | `null` | Filter by specific workflow ID |
| `status` | `string` | `null` | Status filter: `completed`, `failed`, `running`, `cancelled`, `partial_success` |
| `connector` | `string` | `null` | Filter by connector name (e.g. `Salesforce`, `Shopify`, `Postgres`) |
| `source_object` | `string` | `null` | Source object name (e.g. `Order`, `Customer`, `Contact`) |
| `destination_object` | `string` | `null` | Destination object name (e.g. `Invoice`, `Deal`) |
| `http_status` | `int` | `null` | Filter by outbound HTTP status code (e.g. `429`, `500`, `200`) |
| `error_type` | `string` | `null` | Error taxonomy category (e.g. `RATE_LIMIT`, `AUTHENTICATION`, `UPSTREAM_5XX`) |
| `trigger` | `string` | `null` | Trigger source: `manual`, `webhook`, `schedule`, `api` |
| `search` | `string` | `null` | Substring search on error summary, execution ID, or workflow name |
| `start_date` | `string (ISO)` | `null` | Executions started on or after timestamp |
| `end_date` | `string (ISO)` | `null` | Executions started on or before timestamp |
| `sort_by` | `string` | `started_at` | Sort column: `started_at`, `duration_ms`, `records_processed` |
| `sort_order` | `string` | `desc` | Sort order: `asc` or `desc` |

**Example Response (`200 OK`):**
```json
{
  "data": [
    {
      "id": "exec_8f492b10a",
      "workflow_id": "wf_order_sync",
      "workflow_name": "Salesforce to NetSuite Order Sync",
      "status": "failed",
      "trigger": "webhook",
      "started_at": "2026-10-14T12:30:00.000Z",
      "finished_at": "2026-10-14T12:30:04.250Z",
      "duration_ms": 4250.0,
      "source_connector": "Salesforce",
      "destination_connector": "NetSuite",
      "source_object": "Order",
      "destination_object": "SalesOrder",
      "http_method": "POST",
      "api_endpoint": "/services/rest/record/v1/salesOrder",
      "http_status_code": 429,
      "error_type": "RATE_LIMIT",
      "error_code": "NETSUITE_RATE_LIMIT",
      "error_summary": "NetSuite concurrent request limit exceeded. Retry after 60s.",
      "records_read": 150,
      "records_created": 120,
      "records_updated": 0,
      "records_failed": 30,
      "records_processed": 150,
      "retry_count": 1
    }
  ],
  "meta": {
    "page": 1,
    "pageSize": 20,
    "total": 1420
  }
}
```

---

### 2.2 Export Execution Logs as CSV
`GET /api/executions/export`

Streams a secure, tenant-scoped CSV file containing up to 10,000 filtered execution records. Automatically protects against CSV/formula injection attacks by prepending `'` to fields beginning with `=`, `+`, `-`, `@`, `\t`, or `\r`.

**Supported Filters:** Matches all filter parameters from `GET /api/executions` (`workflow_id`, `status`, `connector`, `source_object`, `error_type`, `start_date`, `end_date`, `search`).

**Example Response Headers (`200 OK`):**
```http
Content-Type: text/csv; charset=utf-8
Content-Disposition: attachment; filename="flowsmith-executions-export.csv"
```

**Example CSV Output:**
```csv
execution_id,timestamp,workflow_name,status,duration_ms,source_connector,destination_connector,http_method,http_status_code,records_read,records_processed,records_failed,retry_count,error_summary
exec_8f492b10a,2026-10-14T12:30:00.000Z,Salesforce to NetSuite Order Sync,failed,4250.0,Salesforce,NetSuite,POST,429,150,150,30,1,"NetSuite concurrent request limit exceeded."
```

---

## 3. Execution Inspector & Telemetry Endpoints

### 3.1 Get Execution Step Telemetry
`GET /api/executions/{execution_id}/steps`

Returns normalized step-by-step telemetry records for every DAG node in the execution.

**Example Response (`200 OK`):**
```json
{
  "data": [
    {
      "id": "step_01",
      "node_id": "trigger_webhook",
      "step_name": "Inbound Webhook Listener",
      "node_type": "trigger",
      "sequence_number": 1,
      "status": "success",
      "started_at": "2026-10-14T12:30:00.000Z",
      "completed_at": "2026-10-14T12:30:00.120Z",
      "duration_ms": 120.0,
      "input_record_count": 1,
      "output_record_count": 1,
      "failed_record_count": 0
    },
    {
      "id": "step_02",
      "node_id": "netsuite_create_order",
      "step_name": "Create NetSuite SalesOrder",
      "node_type": "connector",
      "sequence_number": 2,
      "status": "failed",
      "started_at": "2026-10-14T12:30:00.150Z",
      "completed_at": "2026-10-14T12:30:04.250Z",
      "duration_ms": 4100.0,
      "input_record_count": 150,
      "output_record_count": 120,
      "failed_record_count": 30,
      "error_type": "RATE_LIMIT",
      "error_code": "HTTP_429",
      "error_message": "Upstream rate limit exceeded."
    }
  ]
}
```

---

### 3.2 Get Execution Visual Timeline
`GET /api/executions/{execution_id}/timeline`

Returns structured events formatted specifically for the UI DAG Timeline waterfall view, including initial trigger events, step durations, outbound API calls, and terminal execution status.

**Example Response (`200 OK`):**
```json
{
  "data": {
    "status": "failed",
    "duration_ms": 4250.0,
    "events": [
      {
        "type": "trigger",
        "title": "Execution Started via webhook",
        "timestamp": "2026-10-14T12:30:00.000Z"
      },
      {
        "type": "step",
        "step_id": "netsuite_create_order",
        "title": "Create NetSuite SalesOrder",
        "node_type": "connector",
        "status": "failed",
        "duration_ms": 4100.0,
        "error": "Upstream rate limit exceeded.",
        "api_calls": [
          {
            "id": "req_netsuite_1",
            "http_method": "POST",
            "endpoint_url": "https://api.netsuite.com/v1/salesOrder",
            "http_status_code": 429,
            "duration_ms": 4050.0
          }
        ]
      },
      {
        "type": "terminal",
        "title": "Execution failed",
        "status": "failed",
        "timestamp": "2026-10-14T12:30:04.250Z",
        "duration_ms": 4250.0,
        "details": {
          "records_processed": 150,
          "error_summary": "NetSuite concurrent request limit exceeded."
        }
      }
    ]
  }
}
```

---

### 3.3 List Outbound API Telemetry Calls
`GET /api/executions/{execution_id}/requests`

Returns lightweight metadata for all external HTTP requests made by connectors during the execution. Payload bodies are deferred for network efficiency.

**Example Response (`200 OK`):**
```json
{
  "data": [
    {
      "id": "req_7a8b9c",
      "execution_id": "exec_8f492b10a",
      "step_id": "netsuite_create_order",
      "node_id": "netsuite_node",
      "connector_name": "NetSuite",
      "operation": "create_sales_order",
      "http_method": "POST",
      "endpoint_url": "https://api.netsuite.com/v1/salesOrder",
      "http_status_code": 429,
      "duration_ms": 4050.0,
      "is_truncated": false,
      "error_message": "HTTP 429 Too Many Requests",
      "created_at": "2026-10-14T12:30:01.100Z"
    }
  ]
}
```

---

### 3.4 Get API Request & Response Detail
`GET /api/executions/{execution_id}/requests/{request_id}`

Retrieves full request headers, request payload, response headers, response payload, and error diagnostics for a specific HTTP transaction with secret masking.

**Example Response (`200 OK`):**
```json
{
  "data": {
    "id": "req_7a8b9c",
    "execution_id": "exec_8f492b10a",
    "http_method": "POST",
    "endpoint_url": "https://api.netsuite.com/v1/salesOrder?token=[REDACTED]",
    "request_headers": {
      "Authorization": "Bearer [REDACTED]",
      "Content-Type": "application/json"
    },
    "request_payload": {
      "customerId": "CUST-98214",
      "totalAmount": 1450.00,
      "card_number": "[REDACTED]"
    },
    "http_status_code": 429,
    "response_headers": {
      "Content-Type": "application/json",
      "Retry-After": "60"
    },
    "response_payload": {
      "error": {
        "code": "CONCURRENT_REQUEST_LIMIT_EXCEEDED",
        "message": "Maximum concurrent user requests reached. Wait 60 seconds before retrying."
      }
    },
    "duration_ms": 4050.0,
    "is_truncated": false,
    "created_at": "2026-10-14T12:30:01.100Z"
  }
}
```

---

## 4. Replay & Retry Endpoints

### 4.1 List Execution Retry History
`GET /api/executions/{execution_id}/retries`

Returns the sequential chain of retry attempts associated with an execution run.

**Example Response (`200 OK`):**
```json
{
  "data": [
    {
      "id": "retry_01",
      "execution_id": "exec_8f492b10a_r1",
      "original_execution_id": "exec_8f492b10a",
      "retry_execution_id": "exec_8f492b10a_r1",
      "attempt_number": 1,
      "retry_reason": "Rate limit backoff elapsed",
      "retry_trigger": "manual",
      "triggered_by": "admin@flowsmith.local",
      "retry_policy": "exponential_backoff",
      "status": "completed",
      "created_at": "2026-10-14T12:35:00.000Z"
    }
  ]
}
```

---

### 4.2 Retry Failed Execution (Idempotent)
`POST /api/executions/{execution_id}/retry`

Re-runs the exact snapshotted workflow version of a previous execution. Supports client-supplied idempotency keys to guarantee that network duplicates or double-clicks do not create accidental duplicate executions.

**Request Body:**
```json
{
  "idempotency_key": "user_retry_req_9812",
  "reason": "Upstream service restored",
  "retry_policy": "manual"
}
```

**Initial Submission Response (`202 Accepted`):**
```json
{
  "data": {
    "execution_id": "exec_8f492b10a_r1",
    "status": "queued",
    "attempt_number": 1,
    "idempotent_replay": false
  }
}
```

**Repeated Submission Response (`202 Accepted`):**
```json
{
  "data": {
    "execution_id": "exec_8f492b10a_r1",
    "status": "queued",
    "attempt_number": 1,
    "idempotent_replay": true
  }
}
```

---

## 5. Monitoring Dashboard API

### 5.1 Get Monitoring Summary Metrics
`GET /api/monitoring/summary`

Calculates 8 Cyclr-style summary metrics and error taxonomy distribution aggregated across tenant-accessible executions.

**Query Parameters:**
- `start_date` (ISO timestamp)
- `end_date` (ISO timestamp)
- `workflow_id` (string)
- `connector` (string)

**Example Response (`200 OK`):**
```json
{
  "data": {
    "total_executions": 10450,
    "success_count": 9820,
    "failed_count": 480,
    "in_progress_count": 80,
    "partial_success_count": 50,
    "cancelled_count": 20,
    "success_rate_percent": 93.97,
    "average_duration_ms": 342.5,
    "p95_duration_ms": 890.0,
    "total_records_read": 1420500,
    "total_records_processed": 1395200,
    "total_records_failed": 25300,
    "active_retries": 14,
    "error_distribution": {
      "RATE_LIMIT": 220,
      "UPSTREAM_5XX": 140,
      "NETWORK_ERROR": 65,
      "AUTHENTICATION": 35,
      "SCHEMA_VALIDATION": 20
    }
  }
}
```
