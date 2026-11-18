import { Button } from "@/components/ui/button";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";
import { useDebugMarks } from "@/hooks/debug/UseDebugMarks";
import { useAppStore } from "@/store/AppStore";

/** Debug marks (internal copy only): notes pinned on wrong / missing maps and paths, from the right-click menu. */
export function DebugTab() {
	const app = useAppClient();
	const marks = useDebugMarks(true);
	const settings = useSettings();
	const update = useUpdateSettings();
	const s = useAppStore();
	const shown = settings?.layers["Debug marks"] !== false;
	const list = marks.data?.marks ?? [];
	const fail = (e: unknown) => s.showError(e);

	return (
		<div className="flex flex-col gap-3">
			<p className="text-xs text-muted-foreground">
				Right-click a map, a path or an empty spot: Debug. {list.length} mark(s) in {marks.data?.file}
			</p>
			<div className="flex gap-1.5">
				<Button size="xs" variant="outline" onClick={() => update.mutate({ layers: { "Debug marks": !shown } })}>
					{shown ? "Hide on the map" : "Show on the map"}
				</Button>
				<Button
					size="xs"
					variant="destructive"
					disabled={!list.length}
					onClick={() =>
						s.askConfirm({
							title: "Clear all debug marks",
							text: `Delete all ${list.length} debug marks of this atlas? A copy is kept next to the marks file.`,
							yes: "Clear all",
							danger: true,
							onYes: () => void app.clearDebugMarks().catch(fail),
						})
					}
				>
					Clear all…
				</Button>
			</div>
			<ul className="flex flex-col gap-0.5 text-xs">
				{list.map((m) => (
					<li key={m.id} className="flex items-center gap-2">
						<button
							type="button"
							className="flex-1 truncate text-left hover:text-gold"
							onClick={() => s.flyTo(m.x, m.y, 1)}
						>
							D{m.id} {m.kind}: {m.reason}
							{m.note && ` - ${m.note}`} ({m.x.toFixed(0)}, {m.y.toFixed(0)})
						</button>
						<Button size="xs" variant="ghost" onClick={() => void app.deleteDebugMark(m.id).catch(fail)}>
							Delete
						</Button>
					</li>
				))}
			</ul>
		</div>
	);
}
