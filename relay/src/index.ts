/**
 * The Grand Project's live-sharing relay: a Cloudflare Worker. Each room is a Durable Object holding the pages'
 * WebSockets (the hibernation API: a quiet room costs nothing while it waits), forwarding what one page sends to the
 * others (src/RoomCore.ts). Everything forwarded is sealed by the pages with a key the relay never sees.
 *
 *   wss://<worker>/room/<room>?role=share|watch
 */

import { DurableObject } from "cloudflare:workers";
import { admit, announce, forward, type Member, type Role, roleOf } from "./RoomCore";
import { originAllowed, roomOf } from "./Route";

export interface Env {
	ROOMS: DurableObjectNamespace<Room>;
	ALLOWED_ORIGINS: string;
}

export default {
	async fetch(req: Request, env: Env): Promise<Response> {
		const room = roomOf(new URL(req.url).pathname);
		if (!room) return new Response("The Grand Project's live-sharing relay.", { status: 404 });
		if (req.headers.get("Upgrade")?.toLowerCase() !== "websocket")
			return new Response("Expected a WebSocket.", { status: 426 });
		if (!originAllowed(req.headers.get("Origin"), env.ALLOWED_ORIGINS))
			return new Response("Only the app's page may use this relay.", { status: 403 });
		return env.ROOMS.get(env.ROOMS.idFromName(room)).fetch(req);
	},
} satisfies ExportedHandler<Env>;

/** One room: its sharer and watchers, and what goes between them. */
export class Room extends DurableObject<Env> {
	async fetch(req: Request): Promise<Response> {
		const role = roleOf(new URL(req.url).searchParams.get("role"));
		if (!role) return new Response("role: share or watch", { status: 400 });
		const why = admit(this.members(), role);
		if (why) return new Response(why, { status: 409 });
		const [client, server] = Object.values(new WebSocketPair());
		this.ctx.acceptWebSocket(server, [role]);
		announce(this.members());
		return new Response(null, { status: 101, webSocket: client });
	}

	async webSocketMessage(ws: WebSocket, data: string | ArrayBuffer): Promise<void> {
		forward(this.member(ws), this.members(), data);
	}

	async webSocketClose(ws: WebSocket, code: number, reason: string): Promise<void> {
		try {
			ws.close(code, reason);
		} catch {
			// (closed already)
		}
		announce(this.members(ws));
	}

	async webSocketError(ws: WebSocket): Promise<void> {
		announce(this.members(ws));
	}

	/** The room's pages, `except` one leaving. */
	private members(except?: WebSocket): Member[] {
		return this.ctx
			.getWebSockets()
			.filter((ws) => ws !== except && ws.readyState === WebSocket.OPEN)
			.map((ws) => this.member(ws));
	}

	private member(ws: WebSocket): Member {
		return {
			role: this.ctx.getTags(ws)[0] as Role,
			send: (text) => ws.send(text),
			close: (code, reason) => ws.close(code, reason),
		};
	}
}
