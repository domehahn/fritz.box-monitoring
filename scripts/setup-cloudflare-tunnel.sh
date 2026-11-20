#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Cloudflare Tunnel & Zero Trust Setup for FRITZ! Monitoring Stack
# ==============================================================================

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRETS_DIR="${PROJECT_DIR}/secrets"
TOKEN_FILE="${SECRETS_DIR}/cloudflare_tunnel_token.txt"

mkdir -p "${SECRETS_DIR}"

echo "===================================================================="
echo " Cloudflare Zero Trust Tunnel Setup für FRITZ! Monitoring"
echo "===================================================================="
echo ""
echo "Dieses Skript bereitet den sicheren Online-Zugriff über Cloudflare vor."
echo "Weder Port-Forwarding noch offene Firewall-Ports am Router sind nötig!"
echo ""

if [ -f "${TOKEN_FILE}" ] && [ -s "${TOKEN_FILE}" ]; then
    echo "✔ Token-Datei gefunden: ${TOKEN_FILE}"
else
    echo "Schritt 1: Erstelle deinen Tunnel im Cloudflare Zero Trust Dashboard:"
    echo "  1. Gehe zu https://one.dash.cloudflare.com/"
    echo "  2. Navigiere zu: Networks > Tunnels > 'Add a tunnel'"
    echo "  3. Wähle 'Cloudflared' und benenne den Tunnel (z. B. 'fritz-monitoring')"
    echo "  4. Kopiere das Tunnel-Token aus dem angezeigten Befehl"
    echo "     (Der lange Base64-String hinter '--token')"
    echo ""
    read -rp "Bitte füge dein Cloudflare Tunnel Token hier ein: " CF_TOKEN
    echo -n "${CF_TOKEN}" > "${TOKEN_FILE}"
    chmod 600 "${TOKEN_FILE}"
    echo "✔ Token gespeichert in: ${TOKEN_FILE}"
fi

echo ""
echo "Schritt 2: Public Hostname im Cloudflare Dashboard konfigurieren:"
echo "  - Im Cloudflare Dashboard unter deinem Tunnel -> 'Public Hostname' hinzufügen:"
echo "      * Subdomain/Domain: z. B. monitoring.deinedomain.de"
echo "      * Type: HTTP"
echo "      * URL:  grafana:3000   (wichtig: der interne Docker-Containername!)"
echo ""
echo "Schritt 3: Cloudflare Access Application einrichten (Sicherheit):"
echo "  - Unter Zero Trust: Access > Applications > 'Add an application'"
echo "  - Wähle 'Self-hosted'"
echo "  - Application Name: FRITZ! Monitoring"
echo "  - Domain: monitoring.deinedomain.de"
echo "  - Policy: Action 'Allow', Include 'Emails' (deine persönliche E-Mail-Adresse)"
echo ""
echo "Schritt 4: Stack mit Cloudflare-Profil starten:"
echo "  docker compose -f compose.prod.yml --profile cloudflare up -d"
echo ""
echo "✔ Vorbereitung abgeschlossen!"
