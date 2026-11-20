# Cloudflare Zero Trust & Online Monitoring Guide

This guide describes how to securely expose the `fritz.box-monitoring` Grafana stack to the internet using **Cloudflare Tunnel (`cloudflared`)** and **Cloudflare Zero Trust Access**, with zero open inbound ports on your home router.

---

## Architecture

```
[ Remote Browser / Smartphone ]
               │
               ▼ HTTPS (TLS 1.3)
   [ monitoring.yourdomain.com ]
               │
               ▼
   ┌───────────────────────┐
   │ Cloudflare Edge       │ ──▶ Enforces Zero Trust Policy
   │ (Zero Trust Access)   │     (Email PIN, GitHub/Google OAuth, 2FA)
   └───────────┬───────────┘
               │
               ▼ Outbound-only QUIC/TLS tunnel (no port forwarding)
      [ cloudflared ] (Docker Container, profile: cloudflare)
               │
               ▼ Internal Docker network ("ingress")
       [ grafana:3000 ]
               │
               └─▶ Grafana Auth-Proxy trusts 'Cf-Access-Authenticated-User-Email'
                   and logs you in automatically with your admin/viewer account.
```

---

## 1. Prerequisites

1. A domain managed on Cloudflare DNS (Free tier is sufficient).
2. A free Cloudflare Zero Trust account.

---

## 2. Step-by-Step Setup

### Step 1: Create Tunnel in Cloudflare Zero Trust Dashboard
1. Open the [Cloudflare Zero Trust Dashboard](https://one.dash.cloudflare.com/).
2. Navigate to **Networks** ➔ **Tunnels** ➔ Click **Add a tunnel**.
3. Select **Cloudflared** as the connector type and name your tunnel (e.g. `fritz-monitoring`).
4. In the installation instructions, you will see a command containing `--token <TOKEN>`.
5. Copy that token string.

### Step 2: Store Token in Docker Secrets
Run the setup helper script:
```bash
./scripts/setup-cloudflare-tunnel.sh
```
Or manually save the token:
```bash
mkdir -p secrets
echo -n "<YOUR_CLOUDFLARE_TUNNEL_TOKEN>" > secrets/cloudflare_tunnel_token.txt
chmod 600 secrets/cloudflare_tunnel_token.txt
```

### Step 3: Configure Public Hostname Routing
In the Cloudflare Tunnel configuration view:
1. Click the **Public Hostnames** tab.
2. Click **Add a public hostname**.
3. Fill in:
   * **Subdomain**: `monitoring` (or whatever you prefer)
   * **Domain**: `yourdomain.com`
   * **Service Type**: `HTTP`
   * **URL**: `grafana:3000` *(Note: use the internal Docker container hostname, NOT localhost!)*
4. Under **Additional application settings** ➔ **HTTP Settings**:
   * Enable **HTTP2 support**.
   * Leave TLS Verify default.

### Step 4: Protect with Cloudflare Access (SSO / 2FA)
1. Go to **Access** ➔ **Applications** ➔ Click **Add an application**.
2. Select **Self-hosted**.
3. Fill in:
   * **Application name**: `FRITZ! Monitoring`
   * **Application domain**: `monitoring.yourdomain.com`
   * **Session Duration**: e.g., 24 hours.
4. Add a Policy:
   * **Policy name**: `Allow Owner`
   * **Action**: `Allow`
   * **Configure rules**: `Include` ➔ `Emails` ➔ Enter your personal email address.
5. In **Advanced Settings**:
   * Ensure `Send access headers` is checked (`Cf-Access-Authenticated-User-Email`).

### Step 5: Start the Container Stack
Start the stack with the Cloudflare profile:
```bash
docker compose -f compose.prod.yml --env-file .env.production --profile cloudflare up -d
```

---

## 3. Grafana Single Sign-On (Auth Proxy)
The stack is already configured in [compose/core.yml](file:///Users/dominikhahn/dev/workspace/fritz.box-monitoring/compose/core.yml):
```yaml
- GF_AUTH_PROXY_ENABLED=true
- GF_AUTH_PROXY_HEADER_NAME=Cf-Access-Authenticated-User-Email
- GF_AUTH_PROXY_HEADER_PROPERTY=email
- GF_AUTH_PROXY_AUTO_SIGN_UP=true
- GF_AUTH_PROXY_ENABLE_LOGIN_TOKEN=false
```
When you navigate to `https://monitoring.yourdomain.com`, Cloudflare Zero Trust validates your email PIN / OAuth login, forwards the email in the request header, and Grafana instantly logs you in without any second password prompt.

---

## 4. Verification & Troubleshooting

Check the status of the `cloudflared` container:
```bash
docker compose -f compose.prod.yml --profile cloudflare logs cloudflared
```
You should see:
`Registered tunnel connection` and `Connection established`.

To test local readiness:
```bash
docker compose -f compose.prod.yml exec cloudflared wget -qO- http://localhost:2000/ready
```
Output should be `200 OK`.
