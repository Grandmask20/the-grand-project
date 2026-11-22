import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import type { SharedAtlas } from "@/domain/share/SharedAtlas";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import { usePlayer } from "@/hooks/app/UseSettings";
import { sendTo, useShareStore } from "@/store/ShareStore";

/**
 * Sends this atlas to the friends it is shared with (live sharing): whole when a link opens and each time it
 * changes (an add, a fix: the app's "model" event refreshes the maps and landmarks), and where you are each time it
 * moves (I'm here). Only the maps, paths and landmarks go, not the screenshots.
 */
export function useShareHost(): void {
	const app = useAppClient();
	const live = useShareStore((s) =>
		s.links
			.filter((l) => l.role === "share" && l.state === "live")
			.map((l) => l.id)
			.join(","),
	);
	const on = live !== "";
	const state = useAppState().data;
	const graph = useQuery({ queryKey: AppQueryKeys.graph, queryFn: () => app.getGraph(), enabled: on });
	const marks = useQuery({ queryKey: AppQueryKeys.landmarks, queryFn: () => app.getLandmarks(), enabled: on });
	const { player } = usePlayer();
	const info = state?.map ?? null;
	const name = state?.atlas?.name ?? "";

	const atlas = useMemo<SharedAtlas | null>(
		() =>
			info && graph.data && marks.data
				? { name, info, nodes: graph.data.nodes, edges: graph.data.edges, landmarks: marks.data }
				: null,
		[name, info, graph.data, marks.data],
	);

	// each link gets the atlas once per change, and a link newly live gets it at once
	const sentAtlas = useRef(new Map<number, SharedAtlas>());
	const sentPos = useRef(new Map<number, string>());
	useEffect(() => {
		const ids = live ? live.split(",").map(Number) : [];
		for (const k of [...sentAtlas.current.keys()]) if (!ids.includes(k)) sentAtlas.current.delete(k);
		for (const k of [...sentPos.current.keys()]) if (!ids.includes(k)) sentPos.current.delete(k);
		const pos = JSON.stringify(player ? { x: player.x, y: player.y, node: player.node } : null);
		for (const id of ids) {
			if (atlas && sentAtlas.current.get(id) !== atlas) {
				sendTo(id, { t: "atlas", atlas });
				sentAtlas.current.set(id, atlas);
			}
			if (sentPos.current.get(id) !== pos) {
				sendTo(id, { t: "pos", player: JSON.parse(pos) });
				sentPos.current.set(id, pos);
			}
		}
	}, [live, atlas, player]);
}
