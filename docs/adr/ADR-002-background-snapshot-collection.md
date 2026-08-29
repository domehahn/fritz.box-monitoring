# ADR-002: Asynchronous Background Snapshot Collection

## Status

Accepted

## Context

Synchronous TR-064 metrics polling during Prometheus `/metrics` scrapes caused frequent scrape timeouts (5s-10s) and scrape failures when FRITZ!Box CPU load was high or TR-064 responses were slow.

## Decision

Implement an asynchronous background collector loop (`CollectorService`) running every 30 seconds. The collector updates an immutable `MonitoringSnapshot` using thread-safe atomic pointer swaps. The Prometheus `/metrics` endpoint serves metrics directly from the latest in-memory snapshot in under 10ms.

## Consequences

- Scrape latency dropped from >5000ms to <10ms (p95).
- Scrape timeouts eliminated.
- On transient FRITZ!Box network failure, the last valid snapshot is preserved while reporting `fritz_scrape_success=0` and `fritz_consecutive_scrape_failures`.
