# Security Architecture & Operations Guide

## Threat Model & Boundaries

- **TR-064 Interface**: Untrusted/local network interface. Exporter connects using a dedicated, read-only FRITZ!Box user account.
- **Observability Ingress**: Prometheus, Loki, and Exporter HTTP interfaces are unexposed to external networks and isolated within `backend` Docker network.
- **Admin Endpoints**: Device Manager is disabled by default (Compose profile `admin`), requires explicit HTTP Basic/Session auth, validates CSRF tokens on state-changing POST requests, and enforces strict MAC regex validation.
- **Secret Storage**: Passwords are supplied strictly via Docker Secrets (`/run/secrets/*`) or file paths (`*_FILE`). No plaintext passwords are permitted in Docker Compose environment strings, log messages, or exception tracebacks.

---

## Container Hardening Controls

All custom and vendor containers enforce:

- Non-root user execution (`appuser` UID 10001 or vendor non-root user)
- `security_opt: [no-new-privileges:true]`
- Dropped Linux capabilities (`cap_drop: [ALL]`)
- Read-only root filesystems where applicable
- Memory and CPU resource limits to prevent denial-of-service
