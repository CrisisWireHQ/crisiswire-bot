// Cloudflare Worker: Telegram webhook handler for @CrisisWireHQ bot.
//
// Flow:
//  1. Telegram POSTs callback_query when user taps a button.
//  2. Worker validates the secret token, answers callback (toast),
//     edits the message (or caption if photo), and on approval
//     triggers a GitHub repository_dispatch to run the X poster.
//
// Secrets (set via Cloudflare dashboard or `wrangler secret put`):
//   TELEGRAM_BOT_TOKEN
//   TELEGRAM_SECRET_TOKEN
//   GITHUB_TOKEN
//   GITHUB_REPO  (e.g. "CrisisWireHQ/crisiswire-bot")

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("Crisis Wire webhook OK", { status: 200 });
    }

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
      return new Response("ignored", { status: 200 });
    }

    const action = cb.data || "";
    const msg = cb.message || {};
    const chatId = msg.chat?.id;
    const messageId = msg.message_id;
    const callbackId = cb.id;
    const msgText = msg.text || msg.caption || "";
    const isPhoto = !!msg.photo;

    const tg = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}`;
    const editEndpoint = isPhoto ? "editMessageCaption" : "editMessageText";
    const editKey = isPhoto ? "caption" : "text";

    const editPayload = (newText) => {
      const p = {
        chat_id: chatId,
        message_id: messageId,
        [editKey]: newText.slice(0, isPhoto ? 1024 : 4000),
      };
      if (!isPhoto) p.disable_web_page_preview = true;
      return p;
    };

    if (action === "ok") {
      await Promise.all([
        fetch(`${tg}/answerCallbackQuery`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ callback_query_id: callbackId, text: "Queued ✓" }),
        }),
        fetch(`${tg}/${editEndpoint}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(editPayload(`⏳ POSTING...\n\n${msgText}`)),
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
              is_photo: isPhoto,
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
        fetch(`${tg}/${editEndpoint}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(editPayload(`❌ REJECTED\n\n${msgText}`)),
        }),
      ]);
    } else {
      await fetch(`${tg}/answerCallbackQuery`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ callback_query_id: callbackId, text: "?" }),
      });
    }

    return new Response("ok", { status: 200 });
  },
};
