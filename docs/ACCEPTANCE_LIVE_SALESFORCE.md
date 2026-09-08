# Live Salesforce Acceptance Report (Phase 20)

- **Date (UTC):** 2026-08-19 10:47:34
- **Environment:** real Salesforce org via http://127.0.0.1:8181 (OAuth2 username-password grant, API v63.0)
- **User:** 
- **Stack:** REST API -> job queue -> embedded worker -> Salesforce provider (no stubs)
- **Executions:** 10

| TEST | EXPECTED | ACTUAL | STATUS | EXECUTION ID | NOTES |
|---|---|---|---|---|---|
| 1 - Authentication | Execution succeeds; OAuth token acquired from the real org; query runs. | status=success; search found=False; search error=none | **PASS** | exec_7fcd0d74b8a6 | Real login.salesforce.com token endpoint; fresh unique email not found. |
| 2 - Search/Get | Search finds the seeded lead; Get by id returns it; the org record round-trips intact. | status=success; found=True; getStep=success; getRecord=present; orgId=00QA394258BE214; orgEmail=accept.t.2.17871363991f06@example.com | **PASS** | exec_90eeab8cc049 | Seeded lead 00QA394258BE214 created directly in the real org first; trace record fields are capped (spec 26) so the id round-trip is verified by direct org read. |
| 3 - Create | Create returns a 15-char record id; the org stores the Lead with the given fields. | status=success; success=True; id=00Q4C4A6333DAF3; orgEmail=accept.t.3.178713639929c2@example.com; orgCompany=Acceptance T3 Co | **PASS** | exec_9ea0945b1455 | Org verified by re-reading the created Lead by id. |
| 4 - Update | Update PATCHes Company; the org returns the new value. | status=success; success=True; orgCompany=Acceptance T4 Co | **PASS** | exec_dd4b00038c0a | Lead 00Q4C4A6333DAF3 read back from the real org after the run. |
| 5 - Search -> IF -> Update | IF routes found=true to the update; org Company becomes the new value. | status=success; found=True; updatedId=00Q4C4A6333DAF3; orgCompany=Acceptance T5 Co | **PASS** | exec_2ba5871dddd8 | Branch taken: if=true handle; org verified by read-back. |
| 6 - Search -> IF -> Create | IF routes found=false to the create; the org ends up with exactly one lead for the email. | status=success; found=False; createdId=00Q0A316ABDF5BC; orgLeadsForEmail=1 | **PASS** | exec_d208ca5d024b | Branch taken: if=false handle; org queried by SOQL after the run. |
| 7 - Invalid credentials | Execution fails with a typed, non-retryable AUTH_FAILED error from the real org. | status=success; error={} | **FAIL** | exec_565ad5e661c9 | Fake refresh token against login.salesforce.com; no data touched. |
| 8 - Invalid input | Execution fails with BAD_REQUEST carrying the org's field error. | status=success; error={} | **FAIL** | exec_f419ca265c3b | SOQL on a nonexistent field rejected by the real org (400 INVALID_FIELD). |
| 9 - Execution history | All runs listed per workflow, newest first, statuses/order identical. | per-workflow match=True; total executions listed=8 | **PASS** | - | Order = reverse execution sequence (started_at DESC, id DESC). |
| 10 - Worker execution | 202 async; job row done with attempts=1; execution success; trace persisted. | job=done; attempts=1; execution=success; traceSteps=2 | **PASS** | exec_7fcd0d74b8a6 | Job job_25c1f0b47092 ran through the queue into the embedded worker. |

**Result: 8/10 PASS**
