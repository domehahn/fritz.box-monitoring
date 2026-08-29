# Production Readiness Gap Analysis

## Overview

This gap analysis provides an evidence-based assessment of `fritz-avm-client` and `fritz.box-monitoring` against the 120% Production Readiness standard.

---

## Gap Assessment & Remediation Matrix

| Category | Finding / Defect | Priority | Remediation Action | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Packaging & Imports** | `poetry.lock` out of sync with `pyproject.toml` | P0 | Re-synchronize `poetry.lock` using `poetry lock --no-update`. | PENDING |
| **Linting & Typing** | Ruff unused imports in both repos (`client.py`, `router.py`, `app.py`, `prometheus_exporter.py`) | P1 | Auto-fix all ruff warnings (`ruff check --fix`) and enforce clean linting in CI. | PENDING |
| **Type Checking** | `mypy` strict flags not fully declared in `pyproject.toml` | P1 | Enable strict `mypy` checks (`disallow_untyped_defs = true`, `check_untyped_defs = true`). | PENDING |
| **Security & Secrets** | `device_manager` lacks Flask secret key file (`DEVICE_MANAGER_SECRET_KEY_FILE`) and security headers | P1 | Add `DEVICE_MANAGER_SECRET_KEY_FILE`, CSP/HSTS headers, and rate limiting decorator. | PENDING |
| **Audit Logging** | Device deletion actions log raw string messages instead of structured JSON audit events | P1 | Emit structured JSON audit log entries (`{"event": "device_delete", "actor": "...", "target": "...", "result": "..."}`). | PENDING |
| **Operations** | Missing automated production verification script `scripts/verify-production.sh` | P1 | Create executable `scripts/verify-production.sh` checking `/healthz`, `/readyz`, `/metrics`, Loki, and Prometheus. | PENDING |
| **Developer Tooling** | Missing `Makefile` and `.pre-commit-config.yaml` | P2 | Create `Makefile` (`make all`, `make test`, `make lint`) and `.pre-commit-config.yaml`. | PENDING |
| **Architecture Records** | Missing Architecture Decision Records (ADRs) | P2 | Create ADR-001 through ADR-006 under `docs/adr/`. | PENDING |
| **Documentation** | Missing `docs/UPGRADE.md`, `docs/SECURITY_ARCHITECTURE.md`, `docs/GITHUB_REPOSITORY_RULES.md` | P2 | Create operational guides for upgrades, security architecture, and GitHub repository rules. | PENDING |
