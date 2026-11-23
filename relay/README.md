# Live-sharing relay

A small Cloudflare Worker that lets two copies of the app link on any network. The page's direct link (WebRTC) fails when one side's network doesn't allow direct links, such as some mobile, school or work networks. Through the relay, both pages only make an outgoing HTTPS connection, which every network allows.

- **A room** is one Durable Object with one sharer and up to 8 watchers. The sharer's messages go to every watcher, and a watcher's messages go to the sharer.
- **It can't read what it forwards.** The pages seal every message with AES-GCM. The key is part of the invite code and is never sent to the relay.
- **Only the app's page gets in:** the `Origin` must be `http://127.0.0.1` or `http://localhost`, on any port (`ALLOWED_ORIGINS` in `wrangler.toml`).
- **Cost:** the Workers Free plan covers it (Durable Objects included, 100,000 requests a day). On the free plan, going over a limit makes requests fail until the next day; nothing is charged.

## Deploy (once)

1. Make a free Cloudflare account.
2. In `wrangler.toml`, set `name` (the Worker's name). Optionally set `account_id`, or log in instead.
3. Deploy:
   ```bash
   cd relay
   npm install
   npx wrangler login
   npx wrangler deploy
   ```
   It prints the Worker's address, `https://<name>.<account>.workers.dev`.
4. Tell the page where it is: put this in `frontend/.env`, then build the page again (`npm run build` in `frontend`):
   ```
   VITE_SHARE_RELAY_URL=https://<name>.<account>.workers.dev
   ```
   A release built without it offers direct links only.

## Develop

```bash
npm install
npm test          # the room's rules (src/RoomCore.ts) and the Worker's checks (src/Route.ts)
npm run typecheck
npx wrangler dev  # a local relay on http://localhost:8787 (VITE_SHARE_RELAY_URL=http://localhost:8787)
```

## Protocol

`wss://<worker>/room/<room>?role=share|watch`, where `<room>` is 22 URL-safe base64 characters (16 random bytes, made by the sharer's page).

- **Pages send frames** (`ID:I:N:PART`, each up to 60,000 characters plus the seal). Anything else closes the sender (1008).
- **The relay sends `!room:<sharer>:<watchers>`** to everyone each time someone comes or goes: `<sharer>` is 1 when the sharer is in the room, `<watchers>` is how many watch.
- **A second sharer, or a ninth watcher, is refused** (409).
