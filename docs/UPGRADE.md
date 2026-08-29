# Operational Upgrade & Release Guide

## Upgrade Workflow

Follow these steps to upgrade `fritz.box-monitoring` to a new release tag:

1. **Perform Backup**:
   Follow backup steps in [BACKUP_RESTORE.md](BACKUP_RESTORE.md) to back up Grafana and Loki data volumes.

2. **Pull New Container Images**:

   ```bash
   docker compose --env-file .env.production -f compose.prod.yml pull
   ```

3. **Deploy Updated Services**:

   ```bash
   docker compose --env-file .env.production -f compose.prod.yml up -d
   ```

4. **Verify Upgrade Health**:

   ```bash
   ./scripts/verify-production.sh
   ```

---

## Rollback Strategy

If an issue occurs after upgrading:

1. Set `FRITZ_MONITORING_VERSION` in `.env.production` to the previous stable release tag.
2. Re-deploy previous image tag:

   ```bash
   docker compose --env-file .env.production -f compose.prod.yml up -d
   ```

3. Run `./scripts/verify-production.sh` to confirm system recovery.
