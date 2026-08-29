# ADR-001: Canonical AVM/TR-064 Client Abstraction Layer

## Status

Accepted

## Context

Previously, both `fritz-avm-client` and `fritz.box-monitoring` contained redundant TR-064 client code, leading to competing TR-064 polling, code duplication, and inconsistent error handling.

## Decision

`fritz-avm-client` is designated as the **sole canonical TR-064 client SDK**. `fritz.box-monitoring` consumes `fritz-avm-client` exclusively and must never implement direct raw TR-064 calls or rely on `fritzconnection` directly.

## Consequences

- Zero code duplication between client SDK and monitoring stack.
- Single point of maintenance for TR-064 authentication, retries, capabilities, and data normalization.
- Downstream monitoring code relies entirely on typed domain models (`WanStats`, `DslStats`, `WlanStats`, `MeshTopology`).
