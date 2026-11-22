import { XIcon } from "lucide-react";
import type { Map as MapLibreMap, StyleSpecification } from "maplibre-gl";
import { useEffect, useMemo, useState } from "react";
import { Layer, Map as MapGL, Source } from "react-map-gl/maplibre";
import { Button } from "@/components/ui/button";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { friendFeatures, ICON_SCALE } from "@/logic/share/FriendFeatures";
import { useShareStore } from "@/store/ShareStore";

/** The friend's map: black, theirs drawn on it (no ground picture: only maps, paths and landmarks are shared). */
const STYLE: StyleSpecification = {
	version: 8,
	sources: {},
	layers: [{ id: "background", type: "background", paint: { "background-color": "#0b0c0e" } }],
};
/** The colour that is the friend's everywhere (canvas: one colour per friend). */
export const FRIEND = "#5cc8f0";
const LANDMARK = "#c8a45c";

/**
 * A friend's atlas (live sharing), over the map while open: read-only, in its own map (their atlas has its own
 * frame, so it can't lie over yours), updating as they add screenshots and move. Shows their maps with icons, paths
 * and landmarks, and where they are. Their link closing keeps the last atlas they sent, said closed.
 */
export function FriendAtlas() {
	const app = useAppClient();
	const viewing = useShareStore((s) => s.viewing);
	const link = useShareStore((s) => s.links.find((l) => l.id === s.viewing) ?? null);
	const view = useShareStore((s) => s.view);
	const [map, setMap] = useState<MapLibreMap | null>(null);
	const f = useMemo(() => (link?.atlas ? friendFeatures(link.atlas, link.player) : null), [link?.atlas, link?.player]);

	// their icons' pictures, from this app (the same game art), as they come
	const names = f?.iconNames.join("|") ?? "";
	useEffect(() => {
		if (!map || !names) return;
		for (const name of names.split("|")) {
			if (map.hasImage(name)) continue;
			map
				.loadImage(app.spriteUrl(name))
				.then((r) => {
					if (!map.hasImage(name)) map.addImage(name, r.data);
				})
				.catch(() => {});
		}
	}, [map, names, app]);

	// a new atlas opened: the map goes (its frame may differ)
	useEffect(() => {
		if (viewing === null) setMap(null);
	}, [viewing]);

	if (!link || !f || !link.atlas) return null;
	const live = link.state === "live";
	return (
		<section aria-label="Friend's atlas" className="absolute inset-0 z-40 flex flex-col bg-black">
			<header className="flex items-center gap-3 border-b bg-card px-3 py-1.5 text-sm">
				<span className="size-3 rounded-full" style={{ background: FRIEND }} aria-hidden />
				<span className="font-semibold">{link.friend || "Friend"}'s atlas</span>
				<span className="text-muted-foreground">{link.atlas.name}</span>
				<span className="text-xs text-muted-foreground">
					{link.atlas.nodes.length} maps · {link.atlas.landmarks.length} landmarks
				</span>
				<span className={live ? "text-xs text-success-foreground" : "text-xs text-destructive"}>
					{live ? "● live" : "link closed: what they sent last"}
				</span>
				<span className="flex-1" />
				<span className="text-xs text-muted-foreground">read-only</span>
				<Button size="sm" variant="ghost" onClick={() => view(null)} aria-label="Close their atlas">
					<XIcon />
					Close
				</Button>
			</header>
			<div className="relative min-h-0 flex-1">
				<MapGL
					key={link.id}
					mapStyle={STYLE}
					initialViewState={{ bounds: link.atlas.info.bounds, fitBoundsOptions: { padding: 30 } }}
					renderWorldCopies={false}
					attributionControl={false}
					dragRotate={false}
					onLoad={(e) => setMap(e.target)}
				>
					<Source id="friend-paths" type="geojson" data={f.paths}>
						<Layer id="friend-paths" type="line" paint={{ "line-color": "#3a8fb0", "line-width": 2 }} />
					</Source>
					<Source id="friend-maps" type="geojson" data={f.maps}>
						<Layer
							id="friend-maps"
							type="circle"
							paint={{
								"circle-radius": 5,
								"circle-color": "#28dcff",
								"circle-stroke-color": "#000000",
								"circle-stroke-width": 1,
							}}
						/>
					</Source>
					<Source id="friend-icons" type="geojson" data={f.icons}>
						<Layer
							id="friend-icons"
							type="symbol"
							layout={{
								"icon-image": ["get", "name"],
								"icon-size": ICON_SCALE,
								"icon-offset": ["get", "off"],
								"icon-allow-overlap": true,
							}}
						/>
					</Source>
					<Source id="friend-landmarks" type="geojson" data={f.landmarks}>
						<Layer
							id="friend-landmarks"
							type="circle"
							paint={{
								"circle-radius": 11,
								"circle-color": "rgba(0,0,0,0)",
								"circle-stroke-color": LANDMARK,
								"circle-stroke-width": 2.5,
							}}
						/>
					</Source>
					<Source id="friend-here" type="geojson" data={f.here}>
						<Layer
							id="friend-here"
							type="circle"
							paint={{
								"circle-radius": 9,
								"circle-color": FRIEND,
								"circle-stroke-color": "#ffffff",
								"circle-stroke-width": 3,
							}}
						/>
					</Source>
				</MapGL>
				<p className="pointer-events-none absolute bottom-2 left-2 rounded bg-card/80 px-2 py-1 text-xs text-muted-foreground">
					Their maps with their icons, paths and landmarks (gold rings); <span style={{ color: FRIEND }}>●</span> where
					they are.
				</p>
			</div>
		</section>
	);
}
