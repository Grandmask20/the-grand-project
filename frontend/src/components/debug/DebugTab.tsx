import { Trash2Icon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";
import { useDebugMarks } from "@/hooks/debug/UseDebugMarks";
import { useAppStoreCalm } from "@/store/AppStore";

/** Debug marks (internal copy only): notes pinned on wrong / missing maps and paths, from the right-click menu. */
export function DebugTab() {
	const app = useAppClient();
	const marks = useDebugMarks(true);
	const settings = useSettings();
	const update = useUpdateSettings();
	const s = useAppStoreCalm();
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
			{/* in a box of its own, as the icon list and the bookmarks are (user: the marks were a bare list) */}
			{list.length > 0 && (
				<ul className="flex max-h-96 flex-col overflow-y-auto rounded border p-1 text-xs">
					{list.map((m) => (
						<li key={m.id} className="flex items-center gap-2 rounded px-1 py-0.5 hover:bg-accent">
							<span className="w-8 shrink-0 font-mono text-muted-foreground">D{m.id}</span>
							<button
								type="button"
								className="flex-1 truncate text-left hover:text-gold"
								title={`${m.kind}: ${m.reason}${m.note ? ` - ${m.note}` : ""} (${m.x.toFixed(0)}, ${m.y.toFixed(0)})`}
								onClick={() => s.flyTo(m.x, m.y, 1)}
							>
								{`${m.kind}: ${m.reason}${m.note ? ` - ${m.note}` : ""}`}
							</button>
							<button
								type="button"
								aria-label={`Delete D${m.id}`}
								onClick={() => void app.deleteDebugMark(m.id).catch(fail)}
							>
								<Trash2Icon className="size-3.5 text-muted-foreground hover:text-destructive" />
							</button>
						</li>
					))}
				</ul>
			)}
		</div>
	);
}
