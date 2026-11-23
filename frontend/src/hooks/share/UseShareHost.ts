import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import { usePlayer } from "@/hooks/app/UseSettings";
import { useAppStore } from "@/store/AppStore";
import { sendTo, useShareStore } from "@/store/ShareStore";

/** The least time between two atlases sent to a friend (an auto-add of many screenshots changes it each one). */
export const ATLAS_GAP_MS = 3000;

/**
 * Sends this atlas to the friends it is shared with (live sharing), for them to open in their own app as you see it
 * (user: "their map as they see it but w/o ground picture"): the atlas file with your view, packed by the app (GET
 * /api/share/atlas: no screenshots, no map picture), whole when a link opens and each time it changes (the app's
 * "model" event), at most every ATLAS_GAP_MS; where you are (I'm here) and your route, each time they change.
 * A friend's atlas open here is never passed on: theirs to share.
 */
export function useShareHost(): void {
	const app = useAppClient();
	// "id.epoch" of each live share link: a room's epoch goes up as a friend joins, who then needs the atlas whole
	const live = useShareStore((s) =>
		s.links
			.filter((l) => l.role === "share" && l.state === "live")
			.map((l) => `${l.id}.${l.epoch}`)
			.join(","),
	);
	const state = useAppState().data;
	const mine = !!state?.atlas && !state.atlas.friend;
	const on = live !== "" && mine;
	const shared = useQuery({ queryKey: AppQueryKeys.shareAtlas, queryFn: () => app.getShareAtlas(), enabled: on });
	const file = on ? (shared.data?.file ?? null) : null;
	const name = state?.atlas?.name ?? "";
	const { player } = usePlayer();
	const route = useAppStore((s) => s.route?.path ?? null);

	// each link gets each atlas once (kept per "id.epoch": a room's newcomer makes a new key, so everything goes
	// again), position and route as they change
	const sentAtlas = useRef(new Map<string, string>());
	const sentPos = useRef(new Map<string, string>());
	const sentRoute = useRef(new Map<string, string>());
	const lastAtlas = useRef(0);
	const [tick, setTick] = useState(0); // (a held atlas sent once the gap is over)
	useEffect(() => {
		void tick;
		const keys = live ? live.split(",") : [];
		for (const sent of [sentAtlas, sentPos, sentRoute])
			for (const k of [...sent.current.keys()]) if (!keys.includes(k)) sent.current.delete(k);
		const pos = JSON.stringify(mine && player ? { x: player.x, y: player.y, node: player.node } : null);
		const path = JSON.stringify(mine ? route : null);
		const wait = lastAtlas.current + ATLAS_GAP_MS - Date.now();
		let held = false;
		for (const key of keys) {
			const id = Number(key.split(".")[0]);
			const had = sentAtlas.current.get(key);
			// a new link gets it at once; a change waits out the gap
			if (file && had !== file && (had === undefined || wait <= 0)) {
				sendTo(id, { t: "atlas", name, file });
				sentAtlas.current.set(key, file);
				lastAtlas.current = Date.now();
			} else if (file && had !== file) held = true;
			if (sentPos.current.get(key) !== pos) {
				sendTo(id, { t: "pos", player: JSON.parse(pos) });
				sentPos.current.set(key, pos);
			}
			if (sentRoute.current.get(key) !== path) {
				sendTo(id, { t: "route", path: JSON.parse(path) });
				sentRoute.current.set(key, path);
			}
		}
		if (!held) return;
		const t = setTimeout(() => setTick((n) => n + 1), Math.max(0, wait));
		return () => clearTimeout(t);
	}, [live, file, name, player, route, mine, tick]);
}
