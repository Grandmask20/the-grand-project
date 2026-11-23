import { type ComponentProps, type KeyboardEvent, useId } from "react";
import { PagePicker, pageIds } from "@/components/common/PagePicker";
import { Section } from "@/components/common/Section";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import type { Background } from "@/domain/app/UiSettings";
import { useMeta } from "@/hooks/app/UseMeta";
import { usePreviewSettings, useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";
import { useFrames } from "@/hooks/replay/UseFrames";
import { cityColours, landmarkColours, styleColour } from "@/logic/Colours";
import { useAppStore } from "@/store/AppStore";
import { ColourSwatch } from "./ColourSwatch";
import { RevealWhileUsed, useHoldWhileOpen } from "./RevealWhileUsed";
import { SettingSlider } from "./SettingSlider";
import { IconPreview, MapPreview, Path3DPreview, PathPreview } from "./StylePreview";

/** View: what the map shows and how (background, layers, paths, maps, colours, "Colour by"). */
/** Arrow keys in a radio group pick the next / previous choice and move the focus to it (CodeRabbit). */
function radioKeys(e: KeyboardEvent<HTMLDivElement>) {
	const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
	if (!step) return;
	const radios = [...e.currentTarget.querySelectorAll<HTMLButtonElement>('[role="radio"]')];
	const at = radios.indexOf(document.activeElement as HTMLButtonElement);
	const next = radios[(Math.max(at, 0) + step + radios.length) % radios.length];
	if (!next) return;
	e.preventDefault();
	next.focus();
	next.click();
}

export function ViewTab() {
	const meta = useMeta().data;
	const settings = useSettings();
	const update = useUpdateSettings();
	const preview = usePreviewSettings();
	const tint = settings?.style.age_tint ?? "off";
	const tilted = useAppStore((s) => (s.camera?.pitch ?? 0) > 1);
	const iconStyle =
		settings?.style.icon_style === "poe2db art" ? "game art" : String(settings?.style.icon_style ?? "game art");
	// the page kept in the store like the other tabs' pages (PagedTab); not picked yet, it follows the tilt
	const picked = useAppStore((s) => s.pages.view);
	const setPages = useAppStore((s) => s.setPage);
	const page: "2d" | "3d" = picked === "2d" || picked === "3d" ? picked : tilted ? "3d" : "2d";
	const setPage = (k: "2d" | "3d") => setPages("view", k);
	// view settings stay as they are while the timelapse is open (user: changing them while playing or recording
	// changed the replay under it); Colour by stays usable until recording
	const replay = useAppStore((s) => (s.replay ? (s.replay.recording ? "recording" : "open") : null));
	const lock = replay !== null;
	const lockNote = lock && (
		<p className="mb-2 text-xs text-gold">
			{replay === "recording"
				? "View settings are locked while the timelapse records."
				: "View settings are locked while the timelapse is open (Colour by still works); close it to change them."}
		</p>
	);
	const frames = useFrames(tint !== "off");
	const idBase = useId();
	const viewOpen = useAppStore((s) => s.viewOpen);
	const toggleViewSection = useAppStore((s) => s.toggleViewSection);
	if (!meta || !settings) return null;
	const st = settings.style;
	const set = (style: Record<string, string | number | boolean>) => {
		update.mutate({ style });
	};
	// a look shown while its slider is dragged, saved when let go
	const look = (style: Record<string, number>) => {
		preview({ style });
	};
	const bg = settings.ui.background ?? "picture";

	const choice = (label: string, value: string, values: string[], onChange: (v: string) => void) => (
		<div className="flex items-center gap-2">
			<span className="w-24 text-xs text-muted-foreground">{label}</span>
			<HeldSelect value={value} onValueChange={onChange}>
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
			</HeldSelect>
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
				<SettingSlider
					label={label}
					min={lo}
					max={hi}
					step={stepv}
					value={v}
					onPreview={(x) => look({ [key]: x })}
					onCommit={(x) => set({ [key]: x })}
					format={fmt}
				/>
			</div>
		);
	};
	const times = (v: number) => `${v.toFixed(1)}x`;
	// a section that folds (banner's #51, user: "view folds i do like", all folded on first open): its title folds
	// it, its summary says what is set while folded; kept per page in the store
	const fold = (title: string, summary: string) => {
		const key = `${page}:${title}`;
		return {
			foldable: true,
			title,
			summary,
			open: viewOpen.includes(key),
			onToggle: () => toggleViewSection(key),
		};
	};
	const num = (key: string, dflt: number) => Number(st[key] ?? dflt);

	// two pages (user: the 3D view's settings mixed in with the flat map's): the flat map's, and what only the
	// tilted 3D view uses
	const tabs = (
		<PagePicker
			label="View settings"
			pages={[
				["2d", "Map settings"],
				["3d", "3D view settings"],
			]}
			value={page}
			onChange={setPage}
			idBase={idBase}
		/>
	);
	const panel = { id: pageIds(idBase, page).panel, role: "tabpanel", "aria-labelledby": pageIds(idBase, page).tab };

	if (page === "3d")
		return (
			<div className="flex flex-col gap-3">
				{tabs}
				<div {...panel} className="flex flex-col">
					{lockNote}
					{!tilted && (
						<p className="mb-2 text-xs text-gold">These apply in the 3D view (the 3D button, or right-drag to tilt).</p>
					)}
					<RevealWhileUsed layer="Paths" view="3d">
						<Section
							{...fold("Paths", `height ${num("d3_path_lift", 3)} · reach ${times(num("d3_path_far", 2.6))}`)}
							locked={lock}
						>
							<Path3DPreview st={st} meta={meta} />
							{slider("height", "d3_path_lift", 0, 30, 1, 3, (v) => `${v}`)}
							{slider("reach", "d3_path_far", 1, 6, 0.1, 2.6, times)}
							{slider("far thickness", "d3_path_taper", 0.1, 1, 0.05, 0.2, (v) => `${Math.round(v * 100)}%`)}
							{slider("dashes to line", "d3_solid_px", 0, 30, 1, 8, (v) => `${v} px`)}
						</Section>
					</RevealWhileUsed>
					<RevealWhileUsed layer="Icons" view="3d">
						<Section {...fold("Icons", `size ${times(num("d3_icon_size", 1.5))}`)} locked={lock}>
							{slider("reach", "d3_icon_far", 1, 8, 0.1, 2.5, times)}
							{slider("size", "d3_icon_size", 0.5, 2.5, 0.1, 1.5, times)}
						</Section>
					</RevealWhileUsed>
					<Section
						{...fold(
							"Ground",
							num("d3_ground_far", 2.4) ? `fades at ${times(num("d3_ground_far", 2.4))}` : "never fades",
						)}
						locked={lock}
					>
						{slider("fades out at", "d3_ground_far", 0, 6, 0.1, 2.4, (v) => (v ? times(v) : "never"))}
					</Section>
					<RevealWhileUsed layer="3D models" view="3d">
						<Section {...fold("3D models", `size ${times(num("d3_model_size", 1))}`)} locked={lock}>
							{slider("reach", "d3_model_far", 1, 8, 0.1, 2.4, times)}
							{slider("size", "d3_model_size", 0.3, 3, 0.1, 1, times)}
							{slider("height", "d3_model_height", 0.2, 3, 0.1, 0.8, times)}
							<Label className="font-normal">
								<Switch
									checked={st.d3_beams !== false}
									onCheckedChange={(v) => set({ d3_beams: v === true })}
									aria-label="beams over halls and towers"
								/>
								beams over halls and towers
							</Label>
						</Section>
					</RevealWhileUsed>
					<p className="mt-3 text-xs text-muted-foreground">
						Reach and fade: in times the distance from the camera to the middle of the view.
					</p>
					<Button
						size="sm"
						variant="outline"
						className="mt-4 self-start"
						disabled={lock}
						onClick={() => update.mutate({ style: { reset: true } })}
					>
						Reset styles
					</Button>
				</div>
			</div>
		);

	return (
		<div className="flex flex-col gap-3">
			{tabs}
			<div {...panel} className="flex flex-col">
				{lockNote}
				<Section
					{...fold("Background", bg === "picture" ? "Picture" : bg === "vector" ? "Vector" : "Off")}
					locked={lock}
				>
					<div className="flex gap-1.5" role="radiogroup" aria-label="Background" onKeyDown={radioKeys}>
						{(["picture", "vector", "none"] as Background[]).map((b) => (
							<Button
								key={b}
								size="xs"
								role="radio"
								aria-checked={bg === b}
								// (an "off" chosen is red: user)
								variant={bg === b ? (b === "none" ? "destructive" : "default") : "outline"}
								onClick={() => update.mutate({ ui: { background: b } })}
							>
								{b === "picture" ? "Picture" : b === "vector" ? "Vector" : "Off"}
							</Button>
						))}
					</div>
				</Section>

				<Section {...fold("Side panel", (settings.ui.side ?? "left") === "left" ? "Left" : "Right")}>
					<div className="flex gap-1.5" role="radiogroup" aria-label="Side panel" onKeyDown={radioKeys}>
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

				<RevealWhileUsed layer="Paths" view="2d">
					<Section
						{...fold("Paths", `${st.path_style} · ${Number(st.path_width) ? `${st.path_width} px` : "auto width"}`)}
						locked={lock}
					>
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
							<SettingSlider
								label="path width"
								min={0}
								max={8}
								step={1}
								value={Number(st.path_width) || 0}
								onPreview={(v) => look({ path_width: v })}
								onCommit={(v) => set({ path_width: v })}
								format={(v) => (v ? String(v) : "auto")}
								valueWidth="w-6"
							/>
						</div>
						<div className="flex items-center gap-2">
							<span className="w-24 text-xs text-muted-foreground">drawn by at least</span>
							{/* live while dragged (the page hides paths by their share), saved when let go */}
							<SettingSlider
								label="drawn by at least"
								min={0}
								max={100}
								step={5}
								value={Math.round((Number(st.path_freq) || 0) * 100)}
								onPreview={(v) => look({ path_freq: v / 100 })}
								onCommit={(v) => set({ path_freq: v / 100 })}
								format={(v) => `${v}%`}
								valueWidth="w-10"
							/>
						</div>
						<p className="text-xs text-muted-foreground">of the screenshots that show both maps</p>
					</Section>
				</RevealWhileUsed>

				<RevealWhileUsed layer="Icons" view="2d">
					<Section {...fold("Icons", `${iconStyle} · ${times(Number(st.icon_size) || 1)}`)} locked={lock}>
						<IconPreview style={iconStyle} size={Number(st.icon_size) || 1} />
						{choice(
							"style",
							iconStyle,
							// (poe2db's art is the game's own: one choice)
							["game art", "from screenshots", "flat colour", "outline"],
							(v) => set({ icon_style: v }),
						)}
						{slider("size", "icon_size", 0.5, 2.5, 0.1, 1, times)}
					</Section>
				</RevealWhileUsed>

				<RevealWhileUsed layer="Nodes" view="2d">
					<Section {...fold("Maps", `${st.map_style} · ${times(Number(st.map_size) || 1)}`)} locked={lock}>
						<MapPreview st={st} meta={meta} />
						<ColourSwatch
							label="colour"
							value={styleColour(st, "map_col", meta.colours.node.confirmed)}
							onChange={(c) => set({ map_col: c })}
						/>
						{/* (no "hidden": unticking Maps in "Show on the map" does that, user) */}
						{choice("style", st.map_style, ["circles", "squares", "map icons"], (v) => set({ map_style: v }))}
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
							<SettingSlider
								label="map size"
								min={0.5}
								max={2.5}
								step={0.1}
								value={Number(st.map_size) || 1}
								onPreview={(v) => look({ map_size: v })}
								onCommit={(v) => set({ map_size: v })}
							/>
						</div>
					</Section>
				</RevealWhileUsed>

				{/* bookmarks on the map (user): their pins' size, and whether a pin sits on the icon row above its
				    spot or on the map node itself */}
				<RevealWhileUsed layer="Bookmarks" view="2d">
					<Section
						{...fold(
							"Bookmarks",
							`on the ${st.bookmark_at === "map node" ? "map node" : "icon"} · ${times(Number(st.bookmark_size) || 1)}`,
						)}
						locked={lock}
					>
						{slider("size", "bookmark_size", 0.5, 3, 0.1, 1, times)}
						{choice(
							"sits on the",
							st.bookmark_at === "map node" ? "map node" : "icon",
							meta.bookmark_ats ?? ["icon", "map node"],
							(v) => set({ bookmark_at: v }),
						)}
					</Section>
				</RevealWhileUsed>

				<Section {...fold("City biomes and landmarks", "colours")} locked={lock}>
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

				<Section {...fold("Colour by", tint)} locked={replay === "recording"}>
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

				<Button
					size="sm"
					variant="outline"
					className="mt-4 self-start"
					disabled={lock}
					onClick={() => update.mutate({ style: { reset: true } })}
				>
					Reset styles
				</Button>
			</div>
		</div>
	);
}

/** A View dropdown: open, the layer of its section shows (RevealWhileUsed). */
function HeldSelect(props: ComponentProps<typeof Select>) {
	const holdOpen = useHoldWhileOpen();
	return (
		<Select
			{...props}
			onOpenChange={(open) => {
				holdOpen(open);
				props.onOpenChange?.(open);
			}}
		/>
	);
}
