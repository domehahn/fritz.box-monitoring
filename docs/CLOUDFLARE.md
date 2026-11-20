# Cloudflare production access

This stack stays on the Docker host because the exporters need access to the
local FRITZ!Box. Cloudflare publishes only Grafana through an outbound Tunnel;
the host does not open an inbound port. The login is Cloudflare Access, not
Zitadel.

## Cost-optimized target architecture

Use the machine that already runs this Compose stack as the origin:

```text
Browser -> Cloudflare Access (OTP) -> Cloudflare Tunnel -> Docker Grafana
                                      (outbound connection)
FRITZ!Box <- local Docker exporters
```

This avoids a VPS, database, Worker, and separate reverse-proxy host. Cloudflare
states that Tunnel publication does not require a paid Access plan, and its
Zero Trust Free plan is intended for teams below 50 users. For a private,
single-user dashboard this is normally the lowest-cost production setup;
electricity and an optional domain remain the only material costs.

## 1. Create the tunnel

In Cloudflare Zero Trust, create a remotely-managed tunnel and add the public
hostname `agenticstack.eu` with the path `/self/fritz.box*`. Route that route to:

```text
http://grafana:3000
```

The tunnel connector is attached to the Compose `ingress` network, so the
service name resolves inside the stack. Do not route Prometheus, Loki,
Alertmanager, or the Docker socket.

Copy the tunnel token into a local secret file:

```bash
mkdir -p secrets
chmod 700 secrets
umask 077
read -r -s CLOUDFLARE_TUNNEL_TOKEN
printf '%s\n' "$CLOUDFLARE_TUNNEL_TOKEN" > secrets/cloudflare_tunnel_token.txt
unset CLOUDFLARE_TUNNEL_TOKEN
```

The token is a credential. It must not be committed or placed in
`.env.production`.

## 2. Add the login

Create a Cloudflare Access **Self-hosted** application for the exact URL
`https://agenticstack.eu/self/fritz.box/`. Use an Allow policy that includes only the intended email address(es)
or a controlled company domain. Enable **One-time PIN** as the login method.

For the Grafana login, set `GRAFANA_ADMIN_USER` to the authorized address and
put the newly rotated Grafana password only in
`secrets/grafana_admin_password.txt`. Do not put that password in Git, the
`.env.production` file, or Cloudflare configuration. Access OTP and Grafana's
own login are separate controls; keep both enabled for defense in depth.

Do not use an `Everyone` include rule: this would allow any valid email address.
Set a finite session duration and enable MFA if the account policy supports it.
This is the SQUORA-style central edge login boundary, but without Zitadel;
Cloudflare Access owns the session and the origin never receives
unauthenticated traffic.

## 3. Start and verify

```bash
docker compose -f compose.prod.yml --env-file .env.production \
  --profile cloudflare up -d cloudflared

docker compose -f compose.prod.yml --env-file .env.production \
  ps cloudflared
```

Open `https://agenticstack.eu/self/fritz.box/` in a private browser window. The expected sequence is
Cloudflare Access login, then Grafana. Direct access to `127.0.0.1:3000` stays
LAN-local, and the Tunnel does not expose a host port.

For a production rollout, configure health notifications for the Tunnel in
Cloudflare and keep Grafana's own admin password enabled as defense in depth.

