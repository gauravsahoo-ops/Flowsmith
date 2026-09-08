# Disaster Recovery (Phase 33)

> **Claim:** a real, automated drill proves that a `pg_dump` backup of
> this system **restores into an empty database AND repairs a damaged
> one**, with workflows, credentials (decryptable), executions and
> users verified through application code paths afterwards.
> **Not claimed without evidence:** `backend/tests/test_dr/` runs this
> drill on every CI pass; `python -m scripts.dr_drill` runs it on demand.

## Objectives

| Metric | Definition | Current value |
| --- | --- | --- |
| **RPO** | Max data loss window = writes after the last dump | Equal to backup schedule interval (operator-set; hourly cron ⇒ ≤1h). Near-zero requires WAL archiving (see "Upgrades") |
| **RTO** | Time from decision to verified-recovered service | **Measured: ~10 s for the drill dataset** (dump 0.8 s / restore 2.2 s / repair-restore 2.8 s / verify 0.3 s). Scales with DB size; 600 s psql timeout budgeted |

## What is backed up / what it recovers

| Component | Recovery mechanism | Notes |
| --- | --- | --- |
| PostgreSQL (workflows, versions, users, executions, audit, RAG registry) | `pg_dump` → `.sql.gz`; restore via streaming psql | Executions table is authoritative for history |
| Credentials | Rows restore like any data; **plaintext requires `CREDENTIALS_ENCRYPTION_KEY`** — the key lives OUTSIDE the database and must be backed up separately (losing it loses all credential plaintext; rotation documented in `app/security/crypto.py`) | Proven by test: right key decrypts, wrong key raises `CredentialDecryptionError` |
| Workers | Stateless; restart and re-claim. Stale claims requeued automatically (`queue.recover_stale`, tested in `tests/test_queue/test_db_queue.py::test_recover_stale_requeues`) | In-flight jobs at crash time are lost from the queue but their execution rows remain inspectable/re-runnable |
| API | Stateless; restart recovery of pending jobs covered by `test_api/test_async_worker_recovery.py::test_api_restart_recovers_pending_jobs` | |
| Redis | Cache/throttle/queue-transport only. Loss degrades to memory fallbacks (`RedisFailureThrottle`) or empty queue state; no durable data | Queue durability caveat above |
| Vector store (`data/vectors.db`) | Plain file — include in file-level backups; collections registry rows live in Postgres and restore with it | Re-ingest from sources if file is lost |

## The critical lesson baked into the tooling

A naive `psql < dump.sql` over a *damaged* database does NOT repair it:
conflicting primary keys make row copies fail silently in tolerant mode,
so corrupted rows survive. `restore_backup(..., fresh=True)` therefore
drops and recreates the `public` schema before replaying the dump.
The drill damages the target on purpose and asserts
`damage_repaired: true` — this exact failure mode was caught during
development of this phase.

## Runbooks

### Full PostgreSQL loss
1. Provision/verify PostgreSQL; create empty DB.
2. `CREDENTIALS_ENCRYPTION_KEY` present in environment (else credentials unrecoverable).
3. Restore latest dump:
   ```bash
   python -c "from app.utils.backup import restore_backup; \
              restore_backup('backups/<latest>.sql.gz', dsn='$TARGET_DSN', fresh=True)"
   ```
4. Start API + workers (`app.serve`); embedded consumer resumes queue.
5. Spot-check: `GET /api/health`, login, open a workflow, list executions.

### Routine schedule (recommended)
- Nightly `create_backup()` via cron/task scheduler + `prune_backups(keep_days=14)`; ship the `.sql.gz` off-host.
- Weekly: run `python -m scripts.dr_drill` in staging (this IS the restore test).
- Alert when newest backup older than 26 h.

### Drill evidence (last run)
```json
{"ok": true,
 "checks": {"users": true, "workflows": true, "credentials": true,
            "executions": true, "damage_repaired": true},
 "rto_seconds": {"dump": 0.75, "restore": 2.1, "restore_over_damage": 2.78,
                 "verify": 0.22}}
```

## Upgrades (when scale demands)
- WAL archiving / `pgBackRest`/`WAL-G` → RPO ≈ seconds, PITR to any point.
- Off-site object storage with immutability for `.sql.gz` artifacts.
