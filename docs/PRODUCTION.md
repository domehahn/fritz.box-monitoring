# Production Deployment Guide

## Prerequisites

- Docker 24.0+ and Docker Compose v2.20+
- FRITZ!Box with TR-064 enabled
- FRITZ!Box user with read-only monitoring permissions (Least Privilege)

---

## Deployment Steps

1. **Clone repository and configure secrets**:

   ```bash
   mkdir -p secrets
   echo "your_secure_fritz_password" > secrets/fritz_password.txt
   echo "your_secure_grafana_admin_password" > secrets/grafana_admin_password.txt
   echo "your_secure_device_manager_password" > secrets/device_manager_admin_password.txt
   chmod 600 secrets/*.txt
   ```

2. **Configure environment file**:

   ```bash
   cp .env.production.example .env.production
   # Edit .env.production with your FRITZ_HOST, FRITZ_USERNAME, and network bind IP addresses
   ```

3. **Validate Docker Compose configuration**:

   ```bash
   docker compose --env-file .env.production -f compose.prod.yml config
   ```

4. **Launch production stack**:

   ```bash
   docker compose --env-file .env.production -f compose.prod.yml up -d
   ```

5. **Verify deployment health**:

   ```bash
   curl http://127.0.0.1:8000/healthz
   curl http://127.0.0.1:8000/readyz
   curl http://127.0.0.1:3000/api/health
   ```

---

## Upgrades & Rollback

- **Upgrade**:

  ```bash
  docker compose --env-file .env.production -f compose.prod.yml pull
  docker compose --env-file .env.production -f compose.prod.yml up -d
  ```

- **Rollback**:
  Update image tags in `compose.prod.yml` to previous release tag and run `docker compose up -d`.
