# ADR-006: Device Manager Privilege Separation

## Status

Accepted

## Context

Administrative operations (such as host deletion) carry security risk and must not be exposed by default alongside read-only Prometheus metrics collection.

## Decision

Isolate the Device Manager application into a dedicated Docker Compose profile (`admin`), keeping it disabled by default. When enabled, enforce HTTP Basic/Session authentication via `DEVICE_MANAGER_ADMIN_PASSWORD_FILE`, CSRF token validation on state-changing POST requests, HTTP security headers, MAC regex validation, and structured JSON audit logging.

## Consequences

- Monitoring stack runs read-only without administrative privileges by default.
- Privileged operations isolated into an opt-in, hardened security zone.
- All administrative actions generate audit events for security compliance.
