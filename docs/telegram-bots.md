# Telegram bots

The platform runs one or more Telegram bots. All of them are served by the same `bot` process and share one dispatcher; administrators manage them on the **Bots** page of the admin app, which uses `/v1/admin/bots`.

## Registry

Each bot has a name, a Telegram username, an enabled switch and six feature switches:

| Feature | What it turns on |
|---|---|
| `ai_agent` | the AI assistant for linked users |
| `open_ai_agent` | the assistant for guests (public knowledge base only) |
| `commands` | the command menu |
| `notifications` | notifications and one-time codes sent through this bot |
| `announcements` | broadcasts from the admin app |
| `mini_app` | the web app button |

A new bot starts with every feature off. The bot token is stored only in Vault (AppRole `telegram-bots`, one secret per bot under `telegram-bots/`, settings `IHSP_BOT_VAULT__*`); the API shows only `…` and its last four characters. The token in `IHSP_TELEGRAM__BOT_TOKEN` is imported as the default bot, so a deployment with one bot behaves as before.

| Route (admin only, audited) | Purpose |
|---|---|
| `GET /v1/admin/bots` | list bots with features and member counts |
| `POST /v1/admin/bots` | register a bot (`name`, `token`; the token is checked with Telegram) |
| `PATCH /v1/admin/bots/{bot_id}` | rename, enable or disable, change `features` |
| `POST /v1/admin/bots/{bot_id}/rotate-token` | replace the token of the same Telegram bot |
| `POST /v1/admin/bots/announcements` | send a draft broadcast (`broadcast_id`) through the chosen `bot_ids` |

Feature switches apply within 30 seconds. Adding, enabling or rotating a bot needs a restart of the `bot` process. The default bot's token comes from the environment, so rotating it here answers `409` with code `admin/bot-default-token-env`: change the environment and restart.

```bash
curl -X PATCH https://api.example.org/v1/admin/bots/$BOT_ID \
  -H "Authorization: Bearer $ACCESS" -H "Content-Type: application/json" \
  -d '{"features": {"notifications": true, "ai_agent": true}, "otp_code": "123456"}'
```

## Webhook

In production Telegram posts to `/telegram/{secret}` for the default bot, with `IHSP_TELEGRAM__WEBHOOK_SECRET` as the secret-token header. Every other bot gets its own path `/telegram/b/{hmac}` and its own header, both derived from that secret and the bot key with HMAC-SHA256, so one bot's secret cannot post updates as another bot. The bot process registers these webhooks on start. Development uses polling.

Adding a bot, changing it (`PATCH`), replacing its token and sending an announcement need a step-up code (`otp_code`, requested with `POST /v1/id/me/step-up`); a wrong code answers 403 `identity/step-up-invalid`. When Telegram cannot be reached the API answers 503 `admin/bot-telegram-unavailable`, not an invalid token.

## Upgrading an existing server

A server set up before the bot registry has no `telegram-bots` AppRole, and the admin bots page answers `admin/bot-vault-unavailable` until it exists.

1. Unseal Vault, then run the Vault setup again with a root or admin token, as `scripts/prod_init.sh` does: `VAULT_TOKEN=… docker compose --profile tools run --rm -T -e VAULT_TOKEN vault-setup python /init/setup.py --print-credentials`. It is idempotent and creates the `telegram-bots` policy and AppRole beside the identity ones.
2. Copy `IHSP_BOT_VAULT__ROLE_ID` and `IHSP_BOT_VAULT__SECRET_ID` from its output into `.env.prod`; the other `IHSP_BOT_VAULT__*` settings keep their defaults (see `materials/.env.sample`). Never paste them into chat or logs.
3. Deploy, so migration `admin_0005` runs, and restart `api`, `bot` and `worker`. The token in `IHSP_TELEGRAM__BOT_TOKEN` is imported as the default bot on first use.
4. Optional: run `docker compose run --rm api python -m app import-default-bot` (idempotent, never prints the token; exit 0 means the token is in Vault), then delete `IHSP_TELEGRAM__BOT_TOKEN` from `.env.prod` and restart `api`, `bot`, `worker` and `identity`. Without the env token every process uses the default bot's Vault token, and the token of the default bot can be rotated on the Bots page. Keep `IHSP_TELEGRAM__BOT_USERNAME` unless the bot is `@ihspbot`.

## AI answers in Telegram

In a private chat with topics enabled each AI chat is one forum topic. Generated UI blocks are appended as Markdown at the end of the answer message, after the text. HTML widgets replace that only with `IHSP_BOT__WIDGETS_ENABLED=true`; it is off by default.

## Guest Mode

With Bot API 10.0 guest mode a bot answers when someone mentions it (`@bot question`) or replies to it in any chat, even one it is not a member of. The bot answers through `answerGuestQuery` with the public guest assistant: the public knowledge base only, never a user's personal data, even when the caller has a linked account.

- Turn on **Guest Mode** for the bot in @BotFather (Bot Settings). The platform answers only for bots with the `open_ai_agent` feature on.
- A mention that replies to a message sends the quoted text as third-party context: it is cleaned of instruction-like text, never followed as instructions, and links from it are dropped. Links in the answer are kept only when they came from the knowledge base or point to the platform's own hosts.
- Bots, channels and anonymous admins get no answer. During maintenance the bot answers with the maintenance notice.
- Limits: the guest per-minute and per-day limits per Telegram user, plus `IHSP_TELEGRAM__GUEST_CHAT_MESSAGES_PER_MINUTE` per chat (10) and `IHSP_TELEGRAM__GUEST_CHAT_GLOBAL_DAILY_MESSAGES` for all guest-mode answers (1000 a day). The private guest chat keeps its own daily ceiling. After one "limit reached" notice the bot stays silent for a minute.
- Guest-mode updates do not count the caller as a bot member and do not clear the "blocked the bot" mark.

## Notifications

Notifications reach Telegram through the bots that have `notifications` on. When you ask a question in the web assistant and leave the page before the answer is ready, the user gets a `CHAT_ANSWER_READY` notification in Telegram with the start of the question. Legal consent is checked in the bot too: a user who has not accepted the current documents gets a reply with a link to accept.
