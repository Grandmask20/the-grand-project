import {
	BookmarkIcon,
	BookmarkXIcon,
	CastleIcon,
	CrosshairIcon,
	ImageIcon,
	LocateFixedIcon,
	RouteIcon,
	SplineIcon,
	Trash2Icon,
} from "lucide-react";
import { useEffect } from "react";
import { IconPicture } from "@/components/common/IconPicture";
import { MapMark } from "@/components/common/MapMark";
import { Button } from "@/components/ui/button";
import type { ItemInfo } from "@/domain/map/ItemInfo";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useInfo } from "@/hooks/find/UseInfo";
import { useTypes } from "@/hooks/find/UseTypes";
import { useRoutes } from "@/hooks/map/UseRoutes";
import { bookmarkOf, newBookmark } from "@/logic/BookmarkOf";
import { useAppStore } from "@/store/AppStore";

/** What the selection is, as a picture in a ring: the map's own art, an icon's, or a sign for the others. */
function Badge({ info }: { info: ItemInfo }) {
	const inner =
		info.kind === "node" ? (
			<MapMark size={26} />
		) : info.kind === "icon" && info.icon ? (
			<IconPicture name={info.icon} size={28} />
		) : info.kind === "bookmark" ? (
			<BookmarkIcon className="size-5 text-gold" />
		) : info.kind === "landmark" ? (
			<CastleIcon className="size-5 text-gold" />
		) : (
			<SplineIcon className="size-5 text-gold" />
		);
	return (
		<span className="flex size-11 shrink-0 items-center justify-center rounded-full border-2 border-selection bg-background">
			{inner}
		</span>
	);
}

/** The selected map, path, landmark, icon or bookmark (in its window over the map, SelectedPopup; PO's canvas): what
 * it is, its map icons, and every action as a button with its icon and words (PO: no menu in it). */
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
	const iconRows = useTypes().data?.sections.find((s) => s.title === "Map icons")?.rows ?? [];
	// kept fresh: the model changes under it (an add, an edit)
	const fresh = useInfo(selected ? { kind: selected.kind, id: selected.id } : null);
	useEffect(() => {
		if (fresh.isError) select(null);
	}, [fresh.isError, select]);
	const info = fresh.data ?? selected;
	// the bookmark this is, or the one on this map ("★ Bookmarked" made a second one: user)
	const mark = bookmarkOf(info);
	if (!info) return null;
	const node = info.kind === "node" ? info.id : (info.node ?? null);
	// a map's icons, by their names in the type list (the map's paths know them)
	const icons = node !== null ? (routes.graph?.iconsOf(node) ?? []) : [];
	const labelOf = new Map(iconRows.map((r) => [r.icon, r.label]));
	const here = node !== null && routes.player?.node === node;
	const canDelete = info.kind === "landmark" && !info.removed;

	return (
		<div className="flex flex-col gap-3">
			<div className="flex items-center gap-3">
				<Badge info={info} />
				<div className="min-w-0 text-base font-semibold">{info.title}</div>
			</div>
			<div className="text-xs leading-5 text-muted-foreground">
				{info.lines.map((l) => (
					<div key={l}>{l}</div>
				))}
			</div>
			{icons.length > 0 && (
				<div className="flex flex-col gap-1.5">
					<h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Map icons</h3>
					{icons.map((ic) => (
						<span key={ic} className="flex items-center gap-2.5">
							<IconPicture name={ic} size={24} />
							{labelOf.get(ic) ?? ic}
						</span>
					))}
				</div>
			)}
			{/* the actions, words and icons, on as many lines as they need (PO) */}
			<div className="flex flex-wrap items-center gap-1.5">
				{node !== null && (
					<Button size="xs" onClick={() => routes.routeTo(node)}>
						<RouteIcon />
						Route here
					</Button>
				)}
				{info.kind !== "path" && (
					<Button size="xs" variant="outline" onClick={() => editBookmark(mark ?? newBookmark(info, [info.x, info.y]))}>
						<BookmarkIcon />
						{mark ? "★ Edit bookmark" : "Bookmark"}
					</Button>
				)}
				{node !== null && (
					// on your own position it takes it back (an "I'm here" by mistake stayed: user)
					<Button size="xs" variant="outline" onClick={() => (here ? routes.clearPlayer() : routes.setPlayer(node))}>
						<LocateFixedIcon />
						{here ? "I'm not here" : "I'm here"}
					</Button>
				)}
				<Button
					size="xs"
					variant="outline"
					title="Screenshots of this spot"
					onClick={() => showSources([info.x, info.y])}
				>
					<ImageIcon />
					Screenshots
				</Button>
				<Button size="xs" variant="outline" onClick={() => flyTo(info.x, info.y, 1)}>
					<CrosshairIcon />
					Go to
				</Button>
				{mark && (
					<Button
						size="xs"
						variant="outline"
						className="text-destructive"
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
						<BookmarkXIcon />
						Remove bookmark
					</Button>
				)}
				{canDelete && (
					<Button
						size="xs"
						variant="outline"
						className="text-destructive"
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
						<Trash2Icon />
						Delete landmark
					</Button>
				)}
			</div>
			<p className="text-xs text-muted-foreground">Right-click on the map for more (change a landmark, city type…).</p>
		</div>
	);
}
