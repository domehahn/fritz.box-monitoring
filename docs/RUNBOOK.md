# Operations & Incident Response Runbook

## Alert Response Guides

### 1. `FritzExporterDown`

- **Symptom**: Alert fires indicating Prometheus cannot reach `fritz-exporter:8000`.
- **Diagnosis**: Check container status:

  ```bash
  docker compose -f compose.prod.yml ps fritz-exporter
  docker compose -f compose.prod.yml logs --tail=50 fritz-exporter
  ```

- **Recovery**: Restart exporter container:

  ```bash
  docker compose -f compose.prod.yml restart fritz-exporter
  ```

---

### 2. `FritzScrapeFailed` / `FritzSnapshotStale`

- **Symptom**: Metric collection from FRITZ!Box is failing or snapshot age > 180s.
- **Diagnosis**:

  ```bash
  curl http://127.0.0.1:8000/readyz
  ```

  Check exporter logs for network timeouts or authentication errors:

  ```bash
  docker compose -f compose.prod.yml logs fritz-exporter | grep -E "timeout|authentication_error|connection_error"
  ```

- **Recovery**: Verify FRITZ!Box network connectivity and credentials in `secrets/fritz_password.txt`.

---

### 3. `Alloy / Loki Syslog Interruption`

- **Symptom**: No FRITZ!Box syslog entries appear in Grafana Loki dashboard.
- **Diagnosis**:
  - Verify Alloy syslog listener on port 1514:

    ```bash
    docker compose -f compose.prod.yml logs alloy
    ```

  - Verify FRITZ!Box Syslog settings (FRITZ!Box Web UI -> System -> Log -> Syslog server IP).
- **Recovery**: Restart Alloy container:

  ```bash
  docker compose -f compose.prod.yml restart alloy
  ```
