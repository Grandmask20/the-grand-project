import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useRef } from "react";
import type { MapInfo } from "@/domain/map/MapInfo";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useSettings } from "@/hooks/app/UseSettings";
import { type Icon3D, IconLayer3D } from "@/logic/IconLayer3D";
import { useAppStore } from "@/store/AppStore";

/** Puts the 3D view's icons on the map (IconLayer3D) while it is tilted, fed from the tiles' icon_rows layer. */
export function Icons3D({ map, info }: { map: MapLibreMap; info: MapInfo }) {
	const app = useAppClient();
	const settings = useSettings();
	const tilted = useAppStore((s) => (s.camera?.pitch ?? map.getPitch()) > 1);
	const replayPos = useAppStore((s) => (s.replay ? s.replay.pos : null));
	const layer = useRef<IconLayer3D | null>(null);
	const on = tilted && settings?.layers.Icons !== false;
	const models = settings?.layers["3D models"] !== false;

	useEffect(() => {
		if (!on) return;
		const l = new IconLayer3D(info.grid.scale / info.world, async (name) => {
			const r = await map.loadImage(app.spriteUrl(name));
			return r.data as CanvasImageSource;
		});
		layer.current = l;
		map.addLayer(l, "bookmarks");
		let timer = 0;
		const gather = () => {
			timer = 0;
			const seen = new Set<number>();
			const icons: Icon3D[] = [];
			for (const f of map.querySourceFeatures("atlas", { sourceLayer: "icon_rows" })) {
				const p = f.properties ?? {};
				const id = Number(p.id);
				if (seen.has(id) || f.geometry.type !== "Point") continue;
				seen.add(id);
				const [lng, lat] = f.geometry.coordinates as [number, number];
				icons.push({
					lng,
					lat,
					name: String(p.name),
					slot: Number(p.slot) || 0,
					lift: Number(p.lift) || 0,
					step: typeof p.step === "number" ? p.step : -1,
				});
			}
			void l.setIcons(icons);
		};
		const later = (e: { sourceId?: string; isSourceLoaded?: boolean }) => {
			if (e.sourceId === "atlas" && !timer) timer = window.setTimeout(gather, 250);
		};
		map.on("sourcedata", later);
		map.on("moveend", gather);
		gather();
		return () => {
			map.off("sourcedata", later);
			map.off("moveend", gather);
			if (timer) clearTimeout(timer);
			if (map.getLayer(l.id)) map.removeLayer(l.id);
			layer.current = null;
		};
	}, [map, app, info, on]);

	// biome-ignore lint/correctness/useExhaustiveDependencies: `on` re-runs it for a newly made layer
	useEffect(() => {
		const l = layer.current;
		if (!l) return;
		l.models = models;
		l.pos = replayPos ?? 1e9;
		map.triggerRepaint();
	}, [map, models, replayPos, on]);

	return null;
}
