/**
 * Cloudflare Worker: External Synthetic Healthcheck for FRITZ!Box Monitoring
 *
 * Runs every minute from Cloudflare's global edge network.
 * If your home internet or power fails, this worker detects the unreachable
 * tunnel and alerts your phone immediately via Telegram, Pushover, or Discord.
 */

export default {
  // 1. Cron Trigger Handler (runs every minute)
  async scheduled(event, env, ctx) {
    await performHealthCheck(env);
  },

  // 2. HTTP Handler (for manual checks or webhook triggers)
  async fetch(request, env, ctx) {
    const result = await performHealthCheck(env);
    return new Response(JSON.stringify(result, null, 2), {
      headers: { "Content-Type": "application/json" },
      status: result.ok ? 200 : 503,
    });
  },
};

async function performHealthCheck(env) {
  const targetUrl = env.TARGET_URL;
  const timeoutMs = parseInt(env.CHECK_TIMEOUT_MS || "5000", 10);
  const startTime = Date.now();

  let ok = false;
  let status = 0;
  let errorMsg = "";

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(targetUrl, {
      method: "GET",
      signal: controller.signal,
      headers: { "User-Agent": "Cloudflare-Synthetic-Monitor/1.0" },
    });
    clearTimeout(timer);
    status = response.status;
    ok = response.ok;
    if (!ok) {
      errorMsg = `HTTP Status ${status}`;
    }
  } catch (err) {
    clearTimeout(timer);
    errorMsg = err.name === "AbortError" ? "Timeout (>5s)" : err.message;
  }

  const durationMs = Date.now() - startTime;

  if (!ok) {
    const alertTitle = "🚨 HEIMNETZWERK OFFLINE / TOTALAUSFALL";
    const alertMessage =
      `Dein FRITZ! Monitoring Stack unter ${targetUrl} ist von außen nicht mehr erreichbar!\n\n` +
      `Fehler: ${errorMsg}\n` +
      `Dauer: ${durationMs}ms\n` +
      `Mögliche Ursache: Stromausfall, Glasfaser/DSL-Unterbrechung oder Docker-Host down.`;

    await sendNotification(env, alertTitle, alertMessage);
  }

  return { ok, status, durationMs, errorMsg, timestamp: new Date().toISOString() };
}

async function sendNotification(env, title, message) {
  // Telegram
  if (env.TELEGRAM_BOT_TOKEN && env.TELEGRAM_CHAT_ID) {
    try {
      await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chat_id: env.TELEGRAM_CHAT_ID,
          text: `*${title}*\n\n${message}`,
          parse_mode: "Markdown",
        }),
      });
    } catch (_) {}
  }

  // Pushover
  if (env.PUSHOVER_USER_KEY && env.PUSHOVER_API_TOKEN) {
    try {
      const formData = new URLSearchParams();
      formData.append("token", env.PUSHOVER_API_TOKEN);
      formData.append("user", env.PUSHOVER_USER_KEY);
      formData.append("title", title);
      formData.append("message", message);
      formData.append("priority", "2"); // Emergency
      formData.append("retry", "60");
      formData.append("expire", "3600");

      await fetch("https://api.pushover.net/1/messages.json", {
        method: "POST",
        body: formData,
      });
    } catch (_) {}
  }

  // Discord Webhook
  if (env.DISCORD_WEBHOOK_URL) {
    try {
      await fetch(env.DISCORD_WEBHOOK_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          embeds: [
            {
              title: title,
              description: message,
              color: 15158332,
            },
          ],
        }),
      });
    } catch (_) {}
  }
}
