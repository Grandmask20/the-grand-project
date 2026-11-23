/**
 * Where the live-sharing relay is (relay/: a Cloudflare Worker), set when the page is built:
 *
 *   frontend/.env   VITE_SHARE_RELAY_URL=https://<name>.<account>.workers.dev
 *
 * PLACEHOLDER: none is set until the relay is deployed (relay/README.md); the page then offers direct links only.
 * An object, so tests can point it elsewhere.
 */
export const relay = {
	url: String(import.meta.env.VITE_SHARE_RELAY_URL ?? "").replace(/\/+$/, ""),
};

/** Whether rooms through the relay are offered. */
export const relayOn = (): boolean => relay.url !== "";
