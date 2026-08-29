# Production Readiness Gap Analysis — Remediation Plan (August 2026 Audit)

## Executive Summary

A comprehensive audit on August 29, 2026 identified critical P0/P1 gaps in data integrity, CI/CD pipeline failures, fake-zero telemetry masking, container build mismatches, and Alloy syslog pipeline configuration.

---

## Gap Assessment & Remediation Matrix

| Category | Finding / Defect | Priority | Remediation Action | Status |
| :--- | :--- | :--- | :--- | :--- |
| **CI/CD Pipelines** | `fritz-avm-client` and `fritz.box-monitoring` CI workflows fail on ruff/poetry dependencies | P0 | Fix all ruff warnings, decouple relative path dependencies, and ensure green CI across Python 3.10-3.13. | PENDING |
| **Data Integrity** | `get_device_stats()` and sub-clients return fake zero `{'rx_bytes': 0, 'tx_bytes': 0}` or empty `{}` on timeout/error | P0 | Omit fake zero metrics; raise typed exceptions (`FritzTimeoutError`, `FritzConnectionError`) or return `None`. | PENDING |
| **Collector State** | `CollectorService` marks `last_success=now` even when sub-client calls fail or return empty fallbacks | P0 | Mark `last_success` only when collection completely succeeds; increment `consecutive_failures` and record `last_error_type`. | PENDING |
| **Exporter Telemetry** | `FritzPrometheusExporter` converts `None` to `0` (e.g. `bytes or 0`, `is_connected or 0`) | P1 | Omit metric sample series when data is `None`/unknown rather than exporting fake zero gauges. | PENDING |
| **Error Counters** | `fritz_scrape_errors_total` metric is defined but never incremented | P1 | Increment `scrape_errors_total.labels(type=error_type).inc()` on collection and scrape failures. | PENDING |
| **Alloy Syslog Pipeline** | Alloy lacks `syslog_format = "rfc3164"`, `rfc3164_default_to_current_year = true`, and has relabels at wrong stage | P1 | Configure `syslog_format = "rfc3164"`, `rfc3164_default_to_current_year = true`, and place relabel rules directly on `loki.source.syslog`. | PENDING |
| **Device Manager Security** | Admin username is unverified in Basic Auth, direct `client.fc.call_action` used, missing rate limiting | P1 | Verify actor username, encapsulate admin ops in `client.admin.delete_host()`, add rate limiting and secret key fail-fast. | PENDING |
| **Supply Chain & Compose** | `compose.prod.yml` contains `build:` directives; CI lacks Trivy container security scans and SBOM | P0/P1 | Remove `build:` from production compose; add Trivy scanner, Syft SBOM generation, and SHA-pinned GitHub Actions. | PENDING |
| **Developer Tooling** | `Makefile` contains absolute local macOS user paths | P2 | Update `Makefile` to use environment-portable relative paths (`poetry run` / `VENV_BIN`). | PENDING |
