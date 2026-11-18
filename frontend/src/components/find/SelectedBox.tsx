import { useEffect, useRef } from "react";
import { Section } from "@/components/common/Section";
import { Button } from "@/components/ui/button";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useInfo } from "@/hooks/find/UseInfo";
import { useRoutes } from "@/hooks/map/UseRoutes";
import { useAppStore } from "@/store/AppStore";

/** The selected map, path, landmark, icon or bookmark: its details and what can be done with it. */
export function SelectedBox() {
	const app = useAppClient();
	const selected = useAppStore((s) => s.selected);
	const select = useAppStore((s) => s.select);
	const editBookmark = useAppStore((s) => s.editBookmark);
	const showSources = useAppStore((s) => s.showSources);
	const askConfirm = useAppStore((s) => s.askConfirm);
	const showError = useAppStore((s) => s.showError);
	// after a deletion: the selection is cleared only if it is still the deleted item (another one may have been
	// selected while it was deleted: CodeRabbit)
	const clearIf = (gone: { kind: string; id: number }) => {
		const now = useAppStore.getState().selected;
		if (now && now.kind === gone.kind && now.id === gone.id) select(null);
	};
	const flyTo = useAppStore((s) => s.flyTo);
	const routes = useRoutes();
	// kept fresh: the model changes under it (an add, an edit)
	const fresh = useInfo(selected ? { kind: selected.kind, id: selected.id } : null);
	useEffect(() => {
		if (fresh.isError) select(null);
	}, [fresh.isError, select]);
	const info = fresh.data ?? selected;
	// a new selection: the panel scrolls down to show it (user: it stayed out of view under the lists)
	const box = useRef<HTMLDivElement>(null);
	const key = selected ? `${selected.kind}-${selected.id}` : "";
	useEffect(() => {
		if (key) box.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
	}, [key]);

	if (!info) return <p className="text-muted-foreground">Click a map, icon, landmark or bookmark.</p>;
	const node = info.kind === "node" ? info.id : (info.node ?? null);
	return (
		<div ref={box}>
			<Section title="Selected">
				<div className="rounded border bg-card p-2">
					<div className="font-semibold">{info.title}</div>
					{info.lines.map((l) => (
						<div key={l} className="text-xs text-muted-foreground">
							{l}
						</div>
					))}
				</div>
				<div className="flex flex-wrap gap-1.5">
					<Button size="xs" variant="outline" onClick={() => flyTo(info.x, info.y, 1)}>
						Go to
					</Button>
					{info.kind !== "path" && (
						<Button
							size="xs"
							variant="outline"
							onClick={() =>
								editBookmark(
									info.kind === "bookmark"
										? {
												id: info.id,
												x: info.x,
												y: info.y,
												name: info.name ?? "",
												group: info.group ?? "Other",
												note: info.note ?? "",
											}
										: {
												id: null,
												x: info.x,
												y: info.y,
												name: info.suggest?.name ?? info.title,
												group: info.suggest?.group ?? "Other",
												note: "",
											},
								)
							}
						>
							{info.kind === "bookmark" ? "Edit" : info.bookmark != null ? "★ Bookmarked" : "Bookmark"}
						</Button>
					)}
					<Button size="xs" variant="outline" onClick={() => showSources([info.x, info.y])}>
						Screenshots
					</Button>
					{node !== null && (
						<>
							<Button size="xs" variant="outline" onClick={() => routes.routeTo(node)}>
								Route here
							</Button>
							<Button size="xs" variant="outline" onClick={() => routes.setPlayer(node)}>
								I'm here
							</Button>
						</>
					)}
					{info.kind === "bookmark" && (
						<Button
							size="xs"
							variant="destructive"
							onClick={() =>
								askConfirm({
									title: "Delete bookmark",
									text: `Delete "${info.name}"?`,
									yes: "Delete",
									danger: true,
									onYes: () =>
										void app
											.deleteBookmarks([info.id])
											.then(() => clearIf(info))
											.catch(showError),
								})
							}
						>
							Delete
						</Button>
					)}
					{info.kind === "landmark" && !info.removed && (
						<Button
							size="xs"
							variant="destructive"
							onClick={() =>
								askConfirm({
									title: "Delete landmark",
									text: `Delete this ${info.title}? (Kept in the atlas: Layers > Removed shows it.)`,
									yes: "Delete",
									danger: true,
									onYes: () =>
										void app
											.setLandmark(info.x, info.y, "")
											.then(() => clearIf(info))
											.catch(showError),
								})
							}
						>
							Delete
						</Button>
					)}
				</div>
				<p className="text-xs text-muted-foreground">
					Right-click on the map for more (change a landmark, city type…).
				</p>
			</Section>
		</div>
	);
}
