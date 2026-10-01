# WEWE Phase 4C — Backup, Restore and Database Recovery

## Recovery objectives

WEWE uses PostgreSQL as the production database. A logical PostgreSQL custom-format dump is the portable recovery artifact for this application layer.

The repository now provides:

- `scripts/backup_database.sh` — creates a PostgreSQL custom-format dump and validates that the archive is readable.
- `scripts/restore_database.sh` — restores a dump into a separately supplied target database and refuses to run without explicit confirmation.
- CI verification that creates a dump, restores it into a fresh PostgreSQL database, and verifies the restored schema and sentinel data.

These scripts do not manage the PostgreSQL server's physical/WAL backups. Production deployments should additionally enable the managed PostgreSQL provider's automated backups and point-in-time recovery where available.

## Backup procedure

From `backend/`:

```bash
export DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/DB'
./scripts/backup_database.sh ./backups/wewe-$(date -u +%Y%m%dT%H%M%SZ).dump
```

The dump uses PostgreSQL's custom format and excludes ownership/privilege restoration so it can be restored into a separately managed database role.

Backup files may contain the entire customer/order/payment database. Treat them as production secrets:

- use filesystem permissions that restrict access;
- encrypt backups at rest and in transit;
- never commit backups to Git;
- never upload them to public storage;
- retain only according to the production retention policy;
- record and monitor successful/failed backup jobs.

The backup command validates the archive with `pg_restore --list` before reporting success.

## Restore procedure

**Always restore into a new, empty/disposable database first. Never use the restore script directly against the live production database.**

```bash
export DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/LIVE_DB'
export RESTORE_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/RESTORE_DB'
export RESTORE_CONFIRM=YES
./scripts/restore_database.sh ./backups/wewe-YYYYMMDDTHHMMSSZ.dump
```

The restore script:

1. requires an explicit `RESTORE_CONFIRM=YES`;
2. requires a separate target connection string;
3. never drops a database;
4. uses `--exit-on-error`;
5. restores without changing ownership or privileges.

After restoring, run:

```bash
alembic current
alembic upgrade head
```

Then run application smoke tests against the restored database. Verify representative counts for users, products, orders, payments, notification outbox records and audit logs, plus the latest Alembic revision.

## Migration safety

Before an important schema migration:

1. create and archive a fresh database backup;
2. verify the backup archive;
3. apply the migration to a disposable database restored from that backup;
4. run the backend regression suite against the restored database;
5. only then schedule the production migration.

Migrations remain forward-only and must never be edited after application.

## Backup retention

The application repository does not hard-code a production retention period because the correct period depends on the hosting provider, data volume, legal/business requirements and cost. The production infrastructure must explicitly define:

- backup frequency;
- retention duration;
- encryption/key management;
- off-host or cross-region copy policy;
- deletion/lifecycle policy;
- alerting on failed or stale backups;
- restore-test frequency.

A backup policy is incomplete until a restore has been tested.

## CI recovery verification

Phase 4C CI creates a sentinel row, dumps the database, creates a fresh target database, restores the dump, and verifies that the sentinel row and Alembic revision exist in the restored database. This proves the repository's logical backup artifact is readable and restorable with PostgreSQL 16.

## Scope boundary

This slice does not modify payment state transitions, add payment providers, add sandbox adapters, add customer cash payments, or change commerce behavior.
