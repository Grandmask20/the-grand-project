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
import { ColourSwatch } from "./ColourSwatch";
import { LayerToggles } from "./LayerToggles";

/** View: what the map shows and how (background, layers, paths, maps, colours, "Colour by"). */
export function ViewTab() {
	const meta = useMeta().data;
	const settings = useSettings();
	const update = useUpdateSettings();
	const tint = settings?.style.age_tint ?? "off";
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

	return (
		<div className="flex flex-col gap-5">
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

			<Section title="Show on the map">
				<LayerToggles />
			</Section>

			<Section title="Paths">
				<div className="flex flex-wrap items-center gap-3">
					<ColourSwatch label="colour" value={styleColour(st, "path_col", meta.colours.path_multi)} onChange={(c) => set({ path_col: c })} />
					<ColourSwatch label="1 shot" value={styleColour(st, "path_col1", meta.colours.path_single)} onChange={(c) => set({ path_col1: c })} />
				</div>
				{choice("style", st.path_style, ["solid", "dashed", "dotted"], (v) => set({ path_style: v }))}
				<div className="flex items-center gap-2">
					<span className="w-24 text-xs text-muted-foreground">width (0 = auto)</span>
					<Slider min={0} max={8} step={1} value={[Number(st.path_width) || 0]} onValueChange={([v]) => set({ path_width: v })} className="w-36" aria-label="path width" />
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
				<ColourSwatch label="colour" value={styleColour(st, "map_col", meta.colours.node.confirmed)} onChange={(c) => set({ map_col: c })} />
				{choice("style", st.map_style, ["circles", "squares", "hidden"], (v) => set({ map_style: v }))}
				<div className="flex items-center gap-2">
					<span className="w-24 text-xs text-muted-foreground">size</span>
					<Slider min={0.5} max={2.5} step={0.1} value={[Number(st.map_size) || 1]} onValueChange={([v]) => set({ map_size: v })} className="w-36" aria-label="map size" />
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
						<div className="h-2.5 w-56 rounded" style={{ background: `linear-gradient(to right, ${frames.data.ramp.filter((_, i) => i % 16 === 0).join(",")})` }} />
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

			<Button size="sm" variant="outline" className="self-start" onClick={() => update.mutate({ style: { reset: true } })}>
				Reset styles
			</Button>
		</div>
	);
}
