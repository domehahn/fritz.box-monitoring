# Security Architecture & Threat Model

## Threat Model & Boundaries

- **Trust Boundary 1: Local Network / TR-064**: The exporter accesses FRITZ!Box TR-064 over LAN. The exporter uses a dedicated, read-only FRITZ!Box user account.
- **Trust Boundary 2: Observability Network**: Prometheus, Loki, and Exporter operate inside an isolated Docker `backend` network.
- **Trust Boundary 3: Administration Zone**: Device Manager is isolated in Compose profile `admin` and protected by HTTP Basic/Session auth, CSRF tokens, security headers (CSP, HSTS, X-Frame-Options), and MAC address regex validation.

---

## Security Controls Baseline

1. **Secret Management**: Passwords sourced exclusively via `*_FILE` secrets (`/run/secrets/*`). Password scrubbing enforced in logs and exception tracebacks.
2. **Container Security**: Non-root container execution (`appuser` UID 10001), `security_opt: [no-new-privileges:true]`, dropped capabilities (`cap_drop: [ALL]`), and read-only root filesystems.
3. **Audit Logging**: State-changing administrative operations produce structured JSON audit events (`{"event": "device_delete", "actor": "...", "target": "...", "result": "..."}`).
