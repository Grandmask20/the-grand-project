import nodePicture from "@/assets/map_node_icon.webp";
import { useMeta } from "@/hooks/app/UseMeta";
import { useSettings } from "@/hooks/app/UseSettings";
import { styleColour } from "@/logic/Colours";

/**
 * A map as the map draws it, in the style picked in View → Maps (user: Find's results and the selection window drew
 * the game's map art whatever was picked): a circle or a square in the map colour, solid or bordered, or the map
 * art. Hidden maps, or before the settings come, show the map art.
 */
export function MapMark({ size = 22 }: { size?: number }) {
	const st = useSettings()?.style;
	const meta = useMeta().data;
	if (!st || !meta || st.map_style === "map icons" || st.map_style === "hidden")
		return <img src={nodePicture} alt="" width={size} height={size} data-style="map icons" />;
	const colour = styleColour(st, "map_col", meta.colours.node.confirmed);
	const solid = st.map_fill !== "bordered";
	const border = solid ? "rgba(0,0,0,0.55)" : styleColour(st, "map_border", colour);
	// as the map draws a map with no icon colour in it (bordered: that colour inside its border)
	const fill = solid ? colour : meta.colours.no_icon;
	const sw = solid ? 1 : 2.5;
	const r = 10 - sw / 2;
	return (
		<svg viewBox="0 0 24 24" width={size} height={size} aria-hidden data-style={st.map_style} className="shrink-0">
			{st.map_style === "squares" ? (
				<rect x={12 - r} y={12 - r} width={2 * r} height={2 * r} fill={fill} stroke={border} strokeWidth={sw} />
			) : (
				<circle cx={12} cy={12} r={r} fill={fill} stroke={border} strokeWidth={sw} />
			)}
		</svg>
	);
}
