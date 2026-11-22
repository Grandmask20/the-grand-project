import { useMemo } from "react";
import { Source } from "react-map-gl/maplibre";
import { scenePick, selection3d } from "@/domain/map/Scene3D";
import { useSettings } from "@/hooks/app/UseSettings";
import { useInfo } from "@/hooks/find/UseInfo";
import { useMapView } from "@/hooks/map/UseMapView";
import { useScene3D } from "@/hooks/map/UseScene3D";
import { collection, EMPTY, line, point } from "@/logic/map/Features";
import { gotoLayer, hitLayers, selectionLayers } from "@/logic/map/OverlayLayers";
import { useAppStore } from "@/store/AppStore";
import { MapLayer, MapLayers } from "./MapLayer";

/** The selection, Find's results and the go-to mark. */
export function SelectionLayers() {
	const { geo, meta } = useMapView();
	const selected = useAppStore((s) => s.selected);
	const results = useAppStore((s) => s.results);
	// the selection kept fresh, as its box is: the paths lit with a map follow its connections (a connected map deleted
	// stayed lit: CodeRabbit)
	const fresh = useInfo(selected ? { kind: selected.kind, id: selected.id } : null).data;
	const links = (fresh && selected && fresh.kind === selected.kind && fresh.id === selected.id ? fresh : selected)
		?.links;
	const goto = useAppStore((s) => s.goto);
	const settings = useSettings();

	// the flat ring: not for a path (lit up instead), nor while tilted when the 3D view lights the selection up itself
	// (a selected icon wears its ring; a map node's model turns gold: the flat ring lay on the ground under it; it came
	// back wrong after switching views: user)
	const tilted = useAppStore((s) => (s.camera?.pitch ?? 0) > 1);
	const scene = useScene3D(tilted).data;
	const sel = selection3d(selected);
	// (a model of it drawn: a selection without one, e.g. a lone deadly-boss landmark, lost its only mark: CodeRabbit)
	const hasModel = sel.model > 0 && !!scene?.models.some((m) => scenePick(m.pick) === sel.model);
	const lit3d =
		tilted &&
		((sel.icon >= 0 && settings?.layers.Icons !== false) || (hasModel && settings?.layers["3D models"] !== false));
	const ringOn = selected?.kind !== "path" && !lit3d;

	const spot = useMemo(
		() => (selected ? collection([point(geo.toLngLat(selected.x, selected.y))]) : EMPTY),
		[geo, selected],
	);
	// a selected path: the whole path lit up, not a ring where it was clicked (as the old window); a selected map: the
	// paths that connect to it (user: "it could highlight nearby paths which connect to it")
	const path = useMemo(() => {
		const lines =
			selected?.kind === "path" && selected.line?.length ? [selected.line] : (links ?? []).filter((l) => l.length > 1);
		return lines.length ? collection(lines.map((l) => line(l.map(([x, y]) => geo.toLngLat(x, y))))) : EMPTY;
	}, [geo, selected, links]);
	const hits = useMemo(
		() => collection(results.slice(0, 2000).map((r) => point(geo.toLngLat(r.x, r.y)))),
		[geo, results],
	);
	const mark = useMemo(() => (goto ? collection([point(geo.toLngLat(goto[0], goto[1]))]) : EMPTY), [geo, goto]);
	const [pathSpec, ringSpec] = useMemo(() => selectionLayers(geo, meta, ringOn), [geo, meta, ringOn]);
	const hitSpecs = useMemo(() => hitLayers(geo, meta), [geo, meta]);

	return (
		<>
			<Source id="hits" type="geojson" data={hits}>
				<MapLayers specs={hitSpecs} />
			</Source>
			<Source id="selected-path" type="geojson" data={path}>
				<MapLayer spec={pathSpec} />
			</Source>
			<Source id="selected" type="geojson" data={spot}>
				<MapLayer spec={ringSpec} />
			</Source>
			<Source id="goto" type="geojson" data={mark}>
				<MapLayer spec={gotoLayer()} />
			</Source>
		</>
	);
}
