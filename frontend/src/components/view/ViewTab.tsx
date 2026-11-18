import { useState } from "react";
import { Section } from "@/components/common/Section";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import type { Background } from "@/domain/app/UiSettings";
import { useMeta } from "@/hooks/app/UseMeta";
import { useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";
import { useFrames } from "@/hooks/replay/UseFrames";
import { cityColours, landmarkColours, styleColour } from "@/logic/Colours";
import { useAppStore } from "@/store/AppStore";
import { ColourSwatch } from "./ColourSwatch";
import { MapPreview, Path3DPreview, PathPreview } from "./StylePreview";

/** View: what the map shows and how (background, layers, paths, maps, colours, "Colour by"). */
export function ViewTab() {
	const meta = useMeta().data;
	const settings = useSettings();
	const update = useUpdateSettings();
	const tint = settings?.style.age_tint ?? "off";
	const tilted = useAppStore((s) => (s.camera?.pitch ?? 0) > 1);
	const [page, setPage] = useState<"2d" | "3d">(() => (tilted ? "3d" : "2d"));
	const frames = useFrames(tint !== "off");
	if (!meta || !settings) return null;
	const st = settings.style;
	const set = (style: Record<string, string | number | boolean>) => update.mutate({ style });
	const bg = settings.ui.background ?? "picture";

	const choice = (label: string, value: string, values: string[], onChange: (v: string) => void) => (
		<div className="flex items-center gap-2">
			<span className="w-24 text-xs text-muted-foreground">{label}</span>
			<Select value={value} onValueChange={onChange}>
				<SelectTrigger size="sm" className="min-w-36" aria-label={label}>
					<SelectValue />
				</SelectTrigger>
				<SelectContent>
					{values.map((v) => (
						<SelectItem key={v} value={v}>
							{v}
						</SelectItem>
					))}
				</SelectContent>
			</Select>
		</div>
	);

	const slider = (
		label: string,
		key: string,
		lo: number,
		hi: number,
		stepv: number,
		dflt: number,
		fmt: (v: number) => string,
	) => {
		const v = Number(st[key] ?? dflt);
		return (
			<div key={key} className="flex items-center gap-2">
				<span className="w-24 text-xs text-muted-foreground">{label}</span>
				<Slider
					min={lo}
					max={hi}
					step={stepv}
					value={[v]}
					onValueChange={([x]) => set({ [key]: x })}
					className="w-36"
					aria-label={label}
				/>
				<span className="w-12 text-xs">{fmt(v)}</span>
			</div>
		);
	};
	const times = (v: number) => `${v.toFixed(1)}x`;

	// two pages (user: the 3D view's settings mixed in with the flat map's): the flat map's, and what only the
	// tilted 3D view uses
	const tabs = (
		<div className="flex gap-1.5" role="tablist" aria-label="View settings">
			{(["2d", "3d"] as const).map((k) => (
				<Button
					key={k}
					size="xs"
					role="tab"
					aria-selected={page === k}
					variant={page === k ? "default" : "outline"}
					onClick={() => setPage(k)}
				>
					{k === "2d" ? "Map settings" : "3D view settings"}
				</Button>
			))}
		</div>
	);

	if (page === "3d")
		return (
			<div className="flex flex-col gap-5">
				{tabs}
				{!tilted && (
					<p className="text-xs text-gold">These apply in the 3D view (the 3D button, or right-drag to tilt).</p>
				)}
				<Section title="Paths">
					<Path3DPreview st={st} meta={meta} />
					{slider("height", "d3_path_lift", 0, 30, 1, 3, (v) => `${v}`)}
					{slider("reach", "d3_path_far", 1, 6, 0.1, 2.2, times)}
					{slider("far thickness", "d3_path_taper", 0.1, 1, 0.05, 0.35, (v) => `${Math.round(v * 100)}%`)}
					{slider("dashes to line", "d3_solid_px", 0, 30, 1, 9, (v) => `${v} px`)}
				</Section>
				<Section title="Icons">
					{slider("reach", "d3_icon_far", 1, 8, 0.1, 2.6, times)}
					{slider("size", "d3_icon_size", 0.5, 2.5, 0.1, 1, times)}
				</Section>
				<Section title="Ground">
					{slider("fades out at", "d3_ground_far", 0, 6, 0.1, 0, (v) => (v ? times(v) : "never"))}
				</Section>
				<Section title="3D models">
					{slider("reach", "d3_model_far", 1, 8, 0.1, 3, times)}
					{slider("size", "d3_model_size", 0.3, 3, 0.1, 1, times)}
					{slider("height", "d3_model_height", 0.2, 3, 0.1, 1, times)}
					<Label className="font-normal">
						<input
							type="checkbox"
							checked={st.d3_beams !== false}
							onChange={(e) => set({ d3_beams: e.target.checked })}
						/>
						beams over halls and towers
					</Label>
				</Section>
				<p className="text-xs text-muted-foreground">
					Reach and fade: in times the distance from the camera to the middle of the view.
				</p>
				<Button
					size="sm"
					variant="outline"
					className="self-start"
					onClick={() => update.mutate({ style: { reset: true } })}
				>
					Reset styles
				</Button>
			</div>
		);

	return (
		<div className="flex flex-col gap-5">
			{tabs}
			<Section title="Background">
				<div className="flex gap-1.5" role="radiogroup" aria-label="Background">
					{(["picture", "vector", "none"] as Background[]).map((b) => (
						<Button
							key={b}
							size="xs"
							role="radio"
							aria-checked={bg === b}
							variant={bg === b ? "default" : "outline"}
							onClick={() => update.mutate({ ui: { background: b } })}
						>
							{b === "picture" ? "Picture" : b === "vector" ? "Vector" : "Off"}
						</Button>
					))}
				</div>
			</Section>

			<Section title="Side panel">
				<div className="flex gap-1.5" role="radiogroup" aria-label="Side panel">
					{(["left", "right"] as const).map((side) => (
						<Button
							key={side}
							size="xs"
							role="radio"
							aria-checked={(settings.ui.side ?? "left") === side}
							variant={(settings.ui.side ?? "left") === side ? "default" : "outline"}
							onClick={() => update.mutate({ ui: { side } })}
						>
							{side === "left" ? "Left" : "Right"}
						</Button>
					))}
				</div>
				<p className="text-xs text-muted-foreground">
					Drag the panel's edge to resize it (double-click: back to normal).
				</p>
			</Section>

			<Section title="Paths">
				<PathPreview st={st} meta={meta} />
				<div className="flex flex-wrap items-center gap-3">
					<ColourSwatch
						label="colour"
						value={styleColour(st, "path_col", meta.colours.path_multi)}
						onChange={(c) => set({ path_col: c })}
					/>
					<ColourSwatch
						label="1 shot"
						value={styleColour(st, "path_col1", meta.colours.path_single)}
						onChange={(c) => set({ path_col1: c })}
					/>
				</div>
				{choice("style", st.path_style, ["solid", "dashed", "dotted"], (v) => set({ path_style: v }))}
				<div className="flex items-center gap-2">
					<span className="w-24 text-xs text-muted-foreground">width (0 = auto)</span>
					<Slider
						min={0}
						max={8}
						step={1}
						value={[Number(st.path_width) || 0]}
						onValueChange={([v]) => set({ path_width: v })}
						className="w-36"
						aria-label="path width"
					/>
					<span className="w-6 text-xs">{Number(st.path_width) || "auto"}</span>
				</div>
				<div className="flex items-center gap-2">
					<span className="w-24 text-xs text-muted-foreground">drawn by at least</span>
					<Slider
						min={0}
						max={100}
						step={5}
						value={[Math.round((Number(st.path_freq) || 0) * 100)]}
						onValueChange={([v]) => set({ path_freq: v / 100 })}
						className="w-36"
						aria-label="drawn by at least"
					/>
					<span className="w-10 text-xs">{Math.round((Number(st.path_freq) || 0) * 100)}%</span>
				</div>
				<p className="text-xs text-muted-foreground">of the screenshots that show both maps</p>
			</Section>

			<Section title="Maps">
				<MapPreview st={st} meta={meta} />
				<ColourSwatch
					label="colour"
					value={styleColour(st, "map_col", meta.colours.node.confirmed)}
					onChange={(c) => set({ map_col: c })}
				/>
				{choice("style", st.map_style, ["circles", "squares", "map icons", "hidden"], (v) => set({ map_style: v }))}
				{choice("fill", st.map_fill ?? "solid", ["solid", "bordered"], (v) => set({ map_fill: v }))}
				{st.map_fill === "bordered" && (
					<ColourSwatch
						label="border"
						value={styleColour(st, "map_border", styleColour(st, "map_col", meta.colours.node.confirmed))}
						onChange={(c) => set({ map_border: c })}
					/>
				)}
				<div className="flex items-center gap-2">
					<span className="w-24 text-xs text-muted-foreground">size</span>
					<Slider
						min={0.5}
						max={2.5}
						step={0.1}
						value={[Number(st.map_size) || 1]}
						onValueChange={([v]) => set({ map_size: v })}
						className="w-36"
						aria-label="map size"
					/>
				</div>
			</Section>

			<Section title="City biomes and landmarks">
				<div className="grid grid-cols-2 gap-2">
					{Object.entries(cityColours(meta, st)).map(([k, c]) => (
						<ColourSwatch key={k} label={`${k} biome`} value={c} onChange={(v) => set({ [`city_col_${k}`]: v })} />
					))}
					{Object.entries(landmarkColours(meta, st))
						.filter(([k]) => k !== "Locked stronghold")
						.map(([k, c]) => (
							<ColourSwatch key={k} label={k} value={c} onChange={(v) => set({ [`lm_col_${k}`]: v })} />
						))}
				</div>
			</Section>

			<Section title="Colour by">
				{choice("colour by", tint, meta.colour_by, (v) => set({ age_tint: v }))}
				{choice("colours", st.colour_spread, meta.colour_spreads, (v) => set({ colour_spread: v }))}
				<p className="text-xs text-muted-foreground">colours: for oldest to newest and times seen</p>
				{tint === "by session" && frames.data && (
					<div className="flex flex-col gap-1">
						{frames.data.legend.map((l) => (
							<span key={l.label} className="flex items-center gap-2 text-xs">
								<span className="size-3 rounded-full" style={{ background: l.colour }} />
								{l.label}
							</span>
						))}
					</div>
				)}
				{(tint === "oldest to newest" || tint === "times seen") && frames.data && (
					<div className="flex flex-col gap-1">
						<div
							className="h-2.5 w-56 rounded"
							style={{
								background: `linear-gradient(to right, ${frames.data.ramp.filter((_, i) => i % 16 === 0).join(",")})`,
							}}
						/>
						<div className="flex w-56 justify-between text-xs text-muted-foreground">
							<span>{tint === "times seen" ? "seen 1x" : frames.data.oldest}</span>
							<span>{tint === "times seen" ? `${frames.data.heat_top}x` : frames.data.newest}</span>
						</div>
					</div>
				)}
			</Section>

			<Section title="Pictures on the map (zoomed in)">
				<Label className="font-normal">
					<input type="checkbox" checked={!!st.ov_towers} onChange={(e) => set({ ov_towers: e.target.checked })} />
					tower picture
				</Label>
			</Section>

			<Button
				size="sm"
				variant="outline"
				className="self-start"
				onClick={() => update.mutate({ style: { reset: true } })}
			>
				Reset styles
			</Button>
		</div>
	);
}
