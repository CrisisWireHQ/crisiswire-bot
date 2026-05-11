// Cloudflare Worker: Telegram webhook handler for @CrisisWireHQ bot.
//
// Flow:
//  1. Telegram POSTs callback_query to this Worker when user taps a button.
//  2. Worker validates the secret token, answers the callback (toast),
//     edits the message ("⏳ POSTING..." / "❌ REJECTED"), and for approvals
//     triggers a GitHub repository_dispatch event that runs the X poster.
//
// Required secrets (set via Cloudflare dashboard or `wrangler secret put`):
//   TELEGRAM_BOT_TOKEN     — from BotFather
//   TELEGRAM_SECRET_TOKEN  — arbitrary string; same value used in setWebhook
//   GITHUB_TOKEN           — PAT with `repo` (or `public_repo`) scope
//   GITHUB_REPO            — e.g. "CrisisWireHQ/crisiswire-bot"

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("Crisis Wire webhook OK", { status: 200 });
    }

    // Validate Telegram secret token (prevents random POST spam)
    const secret = request.headers.get("x-telegram-bot-api-secret-token");
    if (secret !== env.TELEGRAM_SECRET_TOKEN) {
      return new Response("forbidden", { status: 403 });
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response("bad request", { status: 400 });
    }

    const cb = update.callback_query;
    if (!cb) {
      // Not a callback (probably a /command or text). Ignore for now.
      return new Response("ignored", { status: 200 });
    }

    const action = cb.data || "";
    const msg = cb.message || {};
    const chatId = msg.chat?.id;
    const messageId = msg.message_id;
    const callbackId = cb.id;
    const msgText = msg.text || "";

    const tg = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}`;

    if (action === "ok") {
      // Fire all three in parallel for max speed
      await Promise.all([
        fetch(`${tg}/answerCallbackQuery`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ callback_query_id: callbackId, text: "Queued ✓" }),
        }),
        fetch(`${tg}/editMessageText`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            chat_id: chatId,
            message_id: messageId,
            text: `⏳ POSTING...\n\n${msgText}`,
            disable_web_page_preview: true,
          }),
        }),
        fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`, {
          method: "POST",
          headers: {
            "Accept": "application/vnd.github+json",
            "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "CrisisWireWebhook/1.0",
          },
          body: JSON.stringify({
            event_type: "webhook-approve",
            client_payload: {
              chat_id: chatId,
              message_id: messageId,
              msg_text: msgText,
            },
          }),
        }),
      ]);
    } else if (action === "no") {
      await Promise.all([
        fetch(`${tg}/answerCallbackQuery`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ callback_query_id: callbackId, text: "Rejected." }),
        }),
        fetch(`${tg}/editMessageText`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            chat_id: chatId,
            message_id: messageId,
            text: `❌ REJECTED\n\n${msgText}`,
            disable_web_page_preview: true,
          }),
        }),
      ]);
    } else {
      // Unknown action — just dismiss the loading spinner.
      await fetch(`${tg}/answerCallbackQuery`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ callback_query_id: callbackId, text: "?" }),
      });
    }

    return new Response("ok", { status: 200 });
  },
};
