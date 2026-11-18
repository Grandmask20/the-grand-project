import nodePicture from "@/assets/map_node_icon.webp";
import type { Meta } from "@/domain/app/Meta";
import type { Style } from "@/domain/app/Style";
import { styleColour } from "@/logic/Colours";

/** The live preview strips the old window had above the path and map styles (user: they were missing). */
export function PathPreview({ st, meta }: { st: Style; meta: Meta }) {
	const strong = styleColour(st, "path_col", meta.colours.path_multi);
	const weak = styleColour(st, "path_col1", meta.colours.path_single);
	const w = Number(st.path_width) || 2.5;
	const dash =
		st.path_style === "dashed" ? `${3 * w} ${2 * w}` : st.path_style === "dotted" ? `0.1 ${2 * w}` : undefined;
	const cap = st.path_style === "dotted" ? "round" : "butt";
	const sw = st.path_style === "dotted" ? 1.6 * w : w;
	return (
		<svg viewBox="0 0 240 44" className="h-11 w-full rounded border bg-black" aria-label="Path style preview">
			<polyline
				points="12,30 70,14 128,26"
				fill="none"
				stroke={strong}
				strokeWidth={sw}
				strokeDasharray={dash}
				strokeLinecap={cap}
			/>
			<polyline
				points="128,26 186,12 228,28"
				fill="none"
				stroke={weak}
				strokeWidth={sw}
				strokeDasharray={dash}
				strokeLinecap={cap}
			/>
			{[
				[12, 30],
				[70, 14],
				[128, 26],
				[186, 12],
				[228, 28],
			].map(([x, y]) => (
				<circle key={x} cx={x} cy={y} r={3} fill="#777" />
			))}
		</svg>
	);
}

export function MapPreview({ st, meta }: { st: Style; meta: Meta }) {
	const colour = styleColour(st, "map_col", meta.colours.node.confirmed);
	const solid = st.map_fill !== "bordered";
	const border = solid ? "rgba(0,0,0,0.55)" : styleColour(st, "map_border", colour);
	const size = Number(st.map_size) || 1;
	const r = Math.min(18, 9 * size);
	// a few map nodes: one with each icon colour fill (bordered shows the icon colour inside)
	const fills = solid ? [colour, colour, colour] : ["#c84040", "#4aa0e0", meta.colours.no_icon];
	return (
		<svg viewBox="0 0 240 44" className="h-11 w-full rounded border bg-black" aria-label="Map style preview">
			{fills.map((f, k) => {
				const cx = 60 + k * 60;
				if (st.map_style === "hidden") return null;
				if (st.map_style === "map icons")
					return (
						<image key={cx} href={nodePicture} x={cx - 1.4 * r} y={22 - 1.4 * r} width={2.8 * r} height={2.8 * r} />
					);
				if (st.map_style === "squares")
					return (
						<rect
							key={cx}
							x={cx - r}
							y={22 - r}
							width={2 * r}
							height={2 * r}
							fill={solid ? colour : "none"}
							stroke={solid ? colour : border}
							strokeWidth={2}
						/>
					);
				return <circle key={cx} cx={cx} cy={22} r={r} fill={f} stroke={border} strokeWidth={solid ? 0.8 : 2} />;
			})}
			{st.map_style === "hidden" && (
				<text x={120} y={26} textAnchor="middle" fill="#888" fontSize={11}>
					hidden
				</text>
			)}
		</svg>
	);
}
