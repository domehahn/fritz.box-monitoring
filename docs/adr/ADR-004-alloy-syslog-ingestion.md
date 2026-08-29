# ADR-004: Native Grafana Alloy Syslog Ingestion

## Status

Accepted

## Context

Legacy log ingestion relied on `promtail` and custom Python `log_pusher` scripts polling logs over HTTP/TR-064, creating duplicate log entries and high network overhead.

## Decision

Replace `promtail` and `log_pusher` with Grafana Alloy configured with a native RFC3164 Syslog UDP listener on port 1514 (`loki.source.syslog`). FRITZ!Box routes native syslog messages directly to Grafana Alloy, which processes timestamps, relabels fields, and forwards logs to Loki.

## Consequences

- Zero log polling overhead on FRITZ!Box CPU.
- Preserved native RFC3164 log timestamps and syslog severities.
- Eliminated redundant log pusher sidecar container.
