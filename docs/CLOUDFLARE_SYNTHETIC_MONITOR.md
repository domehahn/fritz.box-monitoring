# Cloudflare Synthetic Healthcheck (External Blackbox Monitor)

This Cloudflare Worker provides **external zero-infrastructure monitoring** of your home network from Cloudflare's global edge network.

---

## Why External Synthetic Monitoring?

If your home network loses power or your ISP connection goes down:
* Your local Alertmanager and Docker containers **cannot send any alerts** (because the internet connection itself is severed).
* This Cloudflare Worker runs completely independently in the cloud every minute.
* If your tunnel or Grafana endpoint (`https://monitoring.yourdomain.com/api/health`) stops answering, you get an immediate push alert on your smartphone.

---

## Deployment (1 Minute)

### 1. Edit Configuration
In `workers/synthetic-monitor/wrangler.jsonc`, configure your public hostname and chosen notification channel:
```jsonc
"vars": {
  "TARGET_URL": "https://monitoring.yourdomain.com/api/health",
  "TELEGRAM_BOT_TOKEN": "123456:ABC...",
  "TELEGRAM_CHAT_ID": "12345678",
  "PUSHOVER_USER_KEY": "...",
  "PUSHOVER_API_TOKEN": "...",
  "DISCORD_WEBHOOK_URL": "..."
}
```

### 2. Deploy with Wrangler
Run in your terminal:
```bash
cd workers/synthetic-monitor
npx wrangler deploy
```

The worker is now active, scheduled to run every 60 seconds (`*/1 * * * *`), and protects you against silent home outages.
