# ADR-005: Single-Node Loki TSDB Storage

## Status

Accepted

## Context

Loki log storage requires a durable, low-overhead persistence schema for single-node HomeLab and small edge deployments without requiring external S3 object storage.

## Decision

Utilize Loki TSDB schema v13 configured with local filesystem storage under `/loki` (`/loki/chunks`, `/loki/rules`, `/loki/index`). Configure automatic 30-day log retention (`720h`) managed by Loki Compactor.

## Consequences

- Zero external S3 storage dependency for single-node deployments.
- Deterministic, volume-backed persistence mounted under `/loki`.
- Storage durability limitations documented in `docs/BACKUP_RESTORE.md` with explicit volume backup commands.
