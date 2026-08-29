# Backup and Disaster Recovery Guide

## Data Persistence Strategy

| Data Asset | Persistent Location | Backup Priority | Disaster Recovery Strategy |
| :--- | :--- | :--- | :--- |
| **Grafana Dashboards & Provisioning** | Git repository (`config/grafana/`) | Low (Infrastructure as Code) | Re-deploy stack from Git repository |
| **Grafana User Data** | `grafana_data` volume | Medium | Backup sqlite3 database or volume |
| **Prometheus Metrics** | `prometheus_data` volume | Low (Regenerable monitoring history) | Periodic volume snapshot or rebuild |
| **Loki Logs** | `loki_data` volume (`/loki`) | Medium | Volume snapshot of `/loki` filesystem |

---

## Backup Procedures

### 1. Grafana Data Backup

```bash
docker run --rm -v fritz-monitoring-prod_grafana_data:/data -v $(pwd):/backup ubuntu tar cvzf /backup/grafana_data_backup.tar.gz /data
```

### 2. Loki Logs Backup

```bash
docker run --rm -v fritz-monitoring-prod_loki_data:/data -v $(pwd):/backup ubuntu tar cvzf /backup/loki_data_backup.tar.gz /data
```

---

## Restore Procedures

```bash
docker compose -f compose.prod.yml down
docker run --rm -v fritz-monitoring-prod_grafana_data:/data -v $(pwd):/backup ubuntu tar xvzf /backup/grafana_data_backup.tar.gz -C /
docker compose -f compose.prod.yml up -d
```
