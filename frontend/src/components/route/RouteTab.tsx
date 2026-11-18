import { Section } from "@/components/common/Section";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useTypes } from "@/hooks/find/UseTypes";
import { useRoutes } from "@/hooks/map/UseRoutes";
import { useAppStore } from "@/store/AppStore";

/** Directions: where you are, the fewest maps to a map or to the nearest map with an icon. */
export function RouteTab() {
	const routes = useRoutes();
	const route = useAppStore((s) => s.route);
	const mode = useAppStore((s) => s.mode);
	const setMode = useAppStore((s) => s.setMode);
	const flyTo = useAppStore((s) => s.flyTo);
	const highlight = useAppStore((s) => s.highlight);
	const setHighlight = useAppStore((s) => s.setHighlight);
	const icons = useTypes().data?.sections.find((s) => s.title === "Map icons")?.rows ?? [];
	const iconOf = new Map(icons.map((r) => [r.icon, r.label]));

	return (
		<div className="flex flex-col gap-5">
			<Section title="You are here">
				<p>{routes.player ? <>map #{routes.player.node}</> : <span className="text-muted-foreground">not set</span>}</p>
				<div className="flex gap-1.5">
					<Button size="xs" variant={mode.kind === "player" ? "default" : "outline"} onClick={() => setMode({ kind: "player" })}>
						Set my position
					</Button>
					{routes.player && (
						<Button size="xs" variant="outline" onClick={() => flyTo(routes.player?.x ?? 0, routes.player?.y ?? 0, 0.5)}>
							Go there
						</Button>
					)}
				</div>
				{mode.kind === "player" && <p className="text-xs text-gold">Click the map you are on (Esc cancels).</p>}
			</Section>

			<Section title="Highlight">
				<Select value={highlight ?? "none"} onValueChange={(v) => setHighlight(v === "none" ? null : v)}>
					<SelectTrigger size="sm" aria-label="Highlight maps with">
						<SelectValue placeholder="maps with…" />
					</SelectTrigger>
					<SelectContent>
						<SelectItem value="none">nothing</SelectItem>
						{icons.map((r) => (
							<SelectItem key={r.icon} value={r.icon}>
								{r.label} ({r.count})
							</SelectItem>
						))}
					</SelectContent>
				</Select>
			</Section>

			<Section title="Route">
				<Select value="" onValueChange={(v) => routes.routeToNearest(v, iconOf.get(v))}>
					<SelectTrigger size="sm" aria-label="Route to the nearest">
						<SelectValue placeholder="to the nearest map with…" />
					</SelectTrigger>
					<SelectContent>
						{icons.map((r) => (
							<SelectItem key={r.icon} value={r.icon}>
								{r.label}
							</SelectItem>
						))}
					</SelectContent>
				</Select>
				<p className="text-xs text-muted-foreground">Or right-click a map: Route here.</p>
				{route && (
					<>
						<p className="font-medium">{route.message}</p>
						<ol className="flex max-h-72 list-decimal flex-col overflow-y-auto pl-6 text-xs">
							{route.path.slice(1).map((id) => {
								const p = routes.graph?.at(id);
								const what = (routes.graph?.iconsOf(id) ?? []).map((n) => iconOf.get(n) ?? n).join(", ");
								return (
									<li key={id}>
										<button type="button" className="hover:text-gold" onClick={() => p && flyTo(p[0], p[1], 0.6)}>
											map #{id}
											{what && <span className="text-muted-foreground"> · {what}</span>}
										</button>
									</li>
								);
							})}
						</ol>
						<Button size="xs" variant="outline" className="self-start" onClick={routes.clear}>
							Clear route
						</Button>
					</>
				)}
			</Section>
		</div>
	);
}
