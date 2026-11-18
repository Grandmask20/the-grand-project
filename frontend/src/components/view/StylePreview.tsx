import nodePicture from "@/assets/map_node_icon.webp";
import type { Meta } from "@/domain/app/Meta";
import type { Style } from "@/domain/app/Style";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useIconArt } from "@/hooks/app/UseIconArt";
import { useTypes } from "@/hooks/find/UseTypes";
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

/**
 * The 3D view's path preview (user): left, a path from map node to map node as up close; right, a path going off
 * into the distance, turning as it goes, getting thinner and fainter by the taper and its dashes becoming a line.
 */
export function Path3DPreview({ st, meta }: { st: Style; meta: Meta }) {
	const strong = styleColour(st, "path_col", meta.colours.path_multi);
	const w = Number(st.path_width) || 3;
	const taper = Number(st.d3_path_taper ?? 0.35);
	const solidPx = Number(st.d3_solid_px ?? 9);
	const dashed = st.path_style === "dashed" || st.path_style === "dotted";
	const on = st.path_style === "dotted" ? 1.5 : 6;
	const off = st.path_style === "dotted" ? 4.5 : 4;
	// the far path: a zigzag going up the box, its scale shrinking with distance (k from 1 near to 0.15 far)
	const steps = 24;
	const pts = Array.from({ length: steps + 1 }, (_, i) => {
		const t = i / steps;
		const k = 1 - 0.85 * t;
		return { x: 200 + Math.sin(t * 7) * 26 * k, y: 42 - t * 40, k, t };
	});
	let along = 0; // length so far, at the near scale: the dashes run on along the path
	return (
		<svg viewBox="0 0 240 44" className="h-11 w-full rounded border bg-black" aria-label="3D path preview">
			<polyline
				points="14,32 54,14 94,30 132,16"
				fill="none"
				stroke={strong}
				strokeWidth={w}
				strokeDasharray={dashed ? `${on * w * 0.5} ${off * w * 0.5}` : undefined}
				strokeLinecap="round"
			/>
			{[14, 54, 94, 132].map((x, i) => (
				<circle key={x} cx={x} cy={[32, 14, 30, 16][i]} r={3} fill="#777" />
			))}
			{pts.slice(1).map((b, i) => {
				const a = pts[i];
				const pattern = (on + off) * w * 0.5 * b.k; // the dash pattern's size on screen there
				const solid = !dashed || pattern < solidPx * 0.5;
				const len = Math.hypot(b.x - a.x, b.y - a.y);
				const offset = along;
				along += len;
				const width = w * (1 - (1 - taper) * b.t) * b.k + 0.5;
				return (
					<line
						key={b.y}
						x1={a.x}
						y1={a.y}
						x2={b.x}
						y2={b.y}
						stroke={strong}
						strokeOpacity={1 - b.t * 0.85}
						strokeWidth={width}
						strokeDasharray={solid ? undefined : `${on * w * 0.5 * b.k} ${off * w * 0.5 * b.k}`}
						strokeDashoffset={solid ? undefined : offset}
						strokeLinecap="round"
					/>
				);
			})}
		</svg>
	);
}

/** The icon style's preview (user): a few of this atlas's icon types in the chosen style and size. */
export function IconPreview({ style, size }: { style: string; size: number }) {
	const app = useAppClient();
	const art = useIconArt();
	const types = useTypes();
	const icons = (types.data?.sections.find((s) => s.title === "Map icons")?.rows ?? [])
		.filter((r) => r.icon && r.icon !== "Unidentified")
		.slice(0, 6)
		.map((r) => r.icon as string);
	const px = Math.round(26 * size);
	return (
		<div
			className="flex w-full items-center justify-center gap-2 overflow-hidden rounded border bg-black"
			style={{ height: Math.max(44, px + 12) }}
			role="img"
			aria-label="Icon style preview"
		>
			{icons.map((n) => (
				<img key={n} src={app.spriteUrl(n, style, art)} alt={n} title={n} width={px} height={px} />
			))}
		</div>
	);
}
