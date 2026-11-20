import { useEffect, useRef } from "react";
import { Section } from "@/components/common/Section";
import { Button } from "@/components/ui/button";
import type { OnLandmark } from "@/domain/map/ItemInfo";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useInfo } from "@/hooks/find/UseInfo";
import { useRoutes } from "@/hooks/map/UseRoutes";
import { bookmarkOf, newBookmark } from "@/logic/BookmarkOf";
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
	// the bookmark this is, or the one on this map ("★ Bookmarked" made a second one: user)
	const mark = bookmarkOf(info);
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
							onClick={() => editBookmark(mark ?? newBookmark(info, [info.x, info.y]))}
						>
							{mark ? "★ Edit bookmark" : "Bookmark"}
						</Button>
					)}
					{mark && (
						<Button
							size="xs"
							variant="destructive"
							onClick={() =>
								askConfirm({
									title: "Remove bookmark",
									text: `Remove the bookmark "${mark.name}"?`,
									yes: "Remove",
									danger: true,
									onYes: () =>
										void app
											.deleteBookmarks([mark.id as number])
											// a bookmark pin goes away with it; a bookmarked map stays selected (user)
											.then(() => info.kind === "bookmark" && clearIf(info))
											.catch(showError),
								})
							}
						>
							Remove bookmark
						</Button>
					)}
					{node !== null && (
						<>
							<Button size="xs" variant="outline" onClick={() => routes.routeTo(node)}>
								Route here
							</Button>
							{/* on your own position it takes it back (an "I'm here" by mistake stayed: user) */}
							{routes.player?.node === node ? (
								<Button size="xs" variant="outline" onClick={routes.clearPlayer}>
									I'm not here
								</Button>
							) : (
								<Button size="xs" variant="outline" onClick={() => routes.setPlayer(node)}>
									I'm here
								</Button>
							)}
						</>
					)}
					<Button size="xs" variant="outline" onClick={() => showSources([info.x, info.y])}>
						Screenshots
					</Button>
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
					{/* a map's own landmark, made a normal map from the map (only the landmark could: user) */}
					{info.on_landmark && (
						<Button
							size="xs"
							variant="destructive"
							onClick={() => {
								const lm = info.on_landmark as OnLandmark;
								askConfirm({
									title: "Normal map",
									text: `Make this ${lm.title} a normal map? (Kept in the atlas: Layers > Removed shows it.)`,
									yes: "Normal map",
									danger: true,
									onYes: () => void app.setLandmark(lm.x, lm.y, "").catch(showError),
								});
							}}
						>
							Not a {info.on_landmark.landmark_kind}
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
