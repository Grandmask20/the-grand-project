import {
	BookmarkIcon,
	ChevronDownIcon,
	ChevronRightIcon,
	ImagesIcon,
	RouteIcon,
	Trash2Icon,
	XIcon,
} from "lucide-react";
import { Fragment, type ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { IconPicture } from "@/components/common/IconPicture";
import { iconGroups } from "@/components/find/ResultRows";
import { Button } from "@/components/ui/button";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { ItemInfo } from "@/domain/map/ItemInfo";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useInfo } from "@/hooks/find/UseInfo";
import { useMapView } from "@/hooks/map/UseMapView";
import { useRoutes } from "@/hooks/map/UseRoutes";
import { bookmarkOf, newBookmark } from "@/logic/BookmarkOf";
import { useAppStore } from "@/store/AppStore";
import { cn } from "@/utils/Cn";

/** Screen px between the selected spot and the box's pointer. */
const GAP = 18;
/** Screen px the box keeps from the map's edges. */
const EDGE = 8;

/** The least a box cut short keeps of its contents, in screen px. */
const LEAST = 80;

/**
 * Where the box goes along the spot's height: above it where it fits, else below where it fits; fitting neither, the
 * side with more room, its contents cut to it (they scroll). `y`: the spot; `H`: the map's height; `h`: the box's whole
 * height; `frame`: its padding and border.
 *
 * @returns Its top, and the height its contents get (null: all of it).
 */
export function boxPlace(y: number, H: number, h: number, frame: number): { top: number; cut: number | null } {
	const above = y - GAP - EDGE;
	const under = H - y - GAP - EDGE;
	const below = h > above && (h <= under || under > above);
	const room = below ? under : above;
	const cut = h > room ? Math.max(LEAST, room - frame) : null;
	const shown = cut === null ? h : cut + frame;
	return { top: below ? y + GAP : y - GAP - shown, cut };
}

/** What deleting a map asks: a map found by the screenshots is kept, shown with Removed; one you added goes for good
 * (app check: it said it could be brought back). */
export function deleteMapText(info: ItemInfo): string {
	const lm = info.on_landmark;
	const what = `Delete map #${info.id}${lm ? ` and its ${lm.title}` : ""}?`;
	return info.added
		? `${what} You added it: it goes for good.`
		: `${what} (Kept in the atlas: Layers > Removed shows it; right-click its spot, Add here > Map, to bring it back.)`;
}

/** "map #222, map #232 and map #333". */
function listOf(items: ReactNode[]): ReactNode {
	return items.map((it, k) => (
		// (the maps are distinct, so their places in the list are too)
		// biome-ignore lint/suspicious/noArrayIndexKey: a sentence's parts, in order
		<Fragment key={k}>
			{k > 0 && (k === items.length - 1 ? " and " : ", ")}
			{it}
		</Fragment>
	));
}

/**
 * The selection, in a box over the map pointing at it (the user's mockup, in the page's look): what it is, its
 * icons, Bookmark / Delete / Route / Screenshots, and its details folded away ("Details": how it was found, the maps
 * it connects to, which light up on the map with it). It follows the map as it moves, above the spot, or below it
 * near the top; off the view, it hides until the spot is back. Outside the map's own element, so the map never takes
 * its clicks, drags or wheel. Goes with the selection (Esc, another atlas).
 */
export function SelectionBox() {
	const selected = useAppStore((s) => s.selected);
	const select = useAppStore((s) => s.select);
	// kept fresh: the model changes under it (an add, an edit)
	const fresh = useInfo(selected ? { kind: selected.kind, id: selected.id } : null);
	// gone, or a map deleted (from the right-click menu too: its box stayed on it, its paths lit: app check)
	const deleted = fresh.data?.kind === "node" && !!fresh.data.removed;
	useEffect(() => {
		if (fresh.isError || deleted) select(null);
	}, [fresh.isError, deleted, select]);
	// (an answer for the selection before, still in the cache: not shown for this one)
	const info = fresh.data && selected && fresh.data.kind === selected.kind ? fresh.data : selected;
	if (!info) return null;
	return <Box info={info} />;
}

function Box({ info }: { info: ItemInfo }) {
	const { geo } = useMapView();
	const map = useAppStore((s) => s.map);
	const box = useRef<HTMLDivElement>(null);
	const inner = useRef<HTMLDivElement>(null);
	const tip = useRef<HTMLSpanElement>(null);
	const [details, setDetails] = useState(false);

	// placed over the spot on every move of the map, straight on the element (not a React draw per frame)
	useLayoutEffect(() => {
		const el = box.current;
		const body = inner.current;
		if (!map || !el || !body) return;
		const place = () => {
			const p = map.project(geo.toLngLat(info.x, info.y));
			const c = map.getContainer();
			const W = c.clientWidth;
			const H = c.clientHeight;
			const w = el.offsetWidth;
			const off = p.x < 0 || p.y < 0 || p.x > W || p.y > H;
			// its whole height (its contents', not as cut short below), and the room above and below the spot: where
			// it fits, above first; fitting neither, the side with more room, its contents scrolling (its details ran
			// past the map's bottom: app check)
			const frame = el.offsetHeight - body.clientHeight;
			const { top, cut } = boxPlace(p.y, H, body.scrollHeight + frame, frame);
			const below = top > p.y;
			body.style.maxHeight = cut === null ? "" : `${cut}px`;
			const left = Math.min(Math.max(EDGE, p.x - w / 2), Math.max(EDGE, W - w - EDGE));
			el.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`;
			el.style.visibility = off ? "hidden" : "visible";
			const t = tip.current;
			if (t) {
				// (measured from inside the box's 10px frame, poking out past it)
				t.style.left = `${Math.min(Math.max(22, p.x - left), w - 22) - 16}px`;
				t.style.top = below ? "-17px" : "";
				t.style.bottom = below ? "" : "-17px";
				t.style.transform = below ? "rotate(225deg)" : "rotate(45deg)";
			}
		};
		place();
		map.on("move", place);
		map.on("resize", place);
		// (its size changes with its details, its icons, a longer name; cut short, only its contents' does)
		const sized = new ResizeObserver(place);
		sized.observe(el);
		if (body.firstElementChild) sized.observe(body.firstElementChild);
		return () => {
			map.off("move", place);
			map.off("resize", place);
			sized.disconnect();
		};
	}, [map, geo, info.x, info.y]);

	return (
		<div
			ref={box}
			role="dialog"
			aria-label={`Selected: ${info.heading ?? info.title}`}
			style={{ visibility: "hidden" }}
			className="poe-panel absolute top-0 left-0 z-10 w-80 max-w-[calc(100%-1rem)] p-3 text-sm text-popover-foreground shadow-float"
		>
			<div ref={inner} className="overflow-y-auto overscroll-contain">
				<Contents info={info} details={details} setDetails={setDetails} />
			</div>
			<span
				ref={tip}
				aria-hidden="true"
				className="absolute size-3 border-r border-b border-[#8a6d38] bg-[var(--panel-colour)]"
			/>
		</div>
	);
}

function Contents({
	info,
	details,
	setDetails,
}: {
	info: ItemInfo;
	details: boolean;
	setDetails: (open: boolean) => void;
}) {
	const app = useAppClient();
	const select = useAppStore((s) => s.select);
	const selectLoaded = useAppStore((s) => s.selectLoaded);
	const flyTo = useAppStore((s) => s.flyTo);
	const editBookmark = useAppStore((s) => s.editBookmark);
	const showSources = useAppStore((s) => s.showSources);
	const askConfirm = useAppStore((s) => s.askConfirm);
	const showError = useAppStore((s) => s.showError);
	const routes = useRoutes();
	const node = info.kind === "node" ? info.id : (info.node ?? null);
	// the bookmark this is, or the one on this map ("★ Bookmarked" made a second one: user)
	const mark = bookmarkOf(info);
	const groups = iconGroups(info.icons ?? []);
	// after a deletion: the selection is cleared only if it is still the deleted item (another one may have been
	// selected while it was deleted: CodeRabbit)
	const clearIf = (gone: { kind: string; id: number }) => {
		const now = useAppStore.getState().selected;
		if (now && now.kind === gone.kind && now.id === gone.id) select(null);
	};
	// another map named here: the map goes there and it is selected
	const goToMap = async (id: number) => {
		const p = routes.graph?.at(id);
		if (p) flyTo(p[0], p[1], 1);
		try {
			await selectLoaded(app.getInfo("node", id));
		} catch (e) {
			showError(e);
		}
	};

	// what Delete deletes: the bookmark, a landmark, the landmark on a map (making it a normal map), or the map itself
	// (user: ghost maps from detection; its landmark goes with it)
	const deletes: { label: string; run: () => void }[] = [];
	if (mark?.id != null) {
		const id = mark.id;
		deletes.push({
			label: "Remove bookmark",
			run: () =>
				askConfirm({
					title: "Remove bookmark",
					text: `Remove the bookmark "${mark.name}"?`,
					yes: "Remove",
					danger: true,
					onYes: () =>
						void app
							.deleteBookmarks([id])
							// a bookmark pin goes away with it; a bookmarked map stays selected (user)
							.then(() => info.kind === "bookmark" && clearIf(info))
							.catch(showError),
				}),
		});
	}
	if (info.kind === "landmark" && !info.removed)
		deletes.push({
			label: "Delete landmark",
			run: () =>
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
				}),
		});
	const lm = info.on_landmark;
	if (lm)
		deletes.push({
			label: `Not a ${lm.landmark_kind}`,
			run: () =>
				askConfirm({
					title: "Normal map",
					text: `Make this ${lm.title} a normal map? (Kept in the atlas: Layers > Removed shows it.)`,
					yes: "Normal map",
					danger: true,
					onYes: () => void app.setLandmark(lm.x, lm.y, "").catch(showError),
				}),
		});
	if (info.kind === "node" && !info.removed)
		deletes.push({
			label: "Delete map",
			run: () =>
				askConfirm({
					title: "Delete map",
					text: deleteMapText(info),
					yes: "Delete map",
					danger: true,
					onYes: () =>
						void app
							.editMap(info.x, info.y, "remove")
							.then(() => clearIf(info))
							.catch(showError),
				}),
		});
	const deleteButton = (
		<Button
			size="xs"
			variant="outline"
			disabled={!deletes.length}
			title={deletes.length ? deletes.map((d) => d.label).join(" / ") : "Nothing here to delete"}
			onClick={deletes.length === 1 ? deletes[0].run : undefined}
		>
			<Trash2Icon className="text-red-400" aria-hidden />
			Delete
		</Button>
	);

	return (
		<div className="flex flex-col gap-2">
			<div className="flex items-start gap-2">
				<div className="min-w-0 flex-1">
					<div className="font-semibold break-words text-gold">{info.heading ?? info.title}</div>
					{info.kind === "icon" && node !== null && (
						<button
							type="button"
							className="text-xs text-muted-foreground hover:text-gold"
							onClick={() => goToMap(node)}
						>
							on map #{node}
						</button>
					)}
				</div>
				<button
					type="button"
					aria-label="Close"
					title="Close (Esc)"
					onClick={() => select(null)}
					className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
				>
					<XIcon className="size-4" />
				</button>
			</div>
			{groups.length > 0 && (
				<div className="flex flex-wrap items-center gap-1.5" title="Map icons">
					{groups.map((g) => (
						<span key={g.name} className="flex items-center gap-0.5" title={g.label}>
							<IconPicture name={g.name} size={20} />
							{g.count > 1 && <span className="text-xs text-muted-foreground">×{g.count}</span>}
						</span>
					))}
				</div>
			)}
			<div className="grid grid-cols-2 gap-1.5">
				<Button
					size="xs"
					variant="outline"
					disabled={info.kind === "path"}
					onClick={() => editBookmark(mark ?? newBookmark(info, [info.x, info.y]))}
				>
					<BookmarkIcon className="text-green-400" aria-hidden />
					{mark ? "Edit bookmark" : "Bookmark"}
				</Button>
				{deletes.length > 1 ? (
					<DropdownMenu>
						<DropdownMenuTrigger asChild>{deleteButton}</DropdownMenuTrigger>
						<DropdownMenuContent>
							{deletes.map((d) => (
								<DropdownMenuItem key={d.label} variant="destructive" onSelect={d.run}>
									{d.label}
								</DropdownMenuItem>
							))}
						</DropdownMenuContent>
					</DropdownMenu>
				) : (
					deleteButton
				)}
				<Button
					size="xs"
					variant="outline"
					disabled={node === null}
					title={node === null ? undefined : `The fewest maps from where you are to map #${node}`}
					onClick={() => node !== null && routes.routeTo(node)}
				>
					<RouteIcon className="text-sky-300" aria-hidden />
					Route here
				</Button>
				<Button size="xs" variant="outline" onClick={() => showSources([info.x, info.y])}>
					<ImagesIcon className="text-blue-400" aria-hidden />
					Screenshots
				</Button>
			</div>
			<button
				type="button"
				aria-expanded={details}
				onClick={() => setDetails(!details)}
				className="flex items-center gap-1 self-start rounded px-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
			>
				{details ? <ChevronDownIcon className="size-3.5" /> : <ChevronRightIcon className="size-3.5" />}
				Details
			</button>
			{details && (
				<div className="flex flex-col gap-2 border-t pt-2 text-xs">
					{info.lines.length > 0 && (
						<div className="flex flex-col gap-0.5">
							<span className="font-semibold text-muted-foreground">
								{info.kind === "node" ? "How it was found" : "About it"}
							</span>
							{info.lines.map((l) => (
								<span key={l} className={cn(l.startsWith("  ") && "pl-3")}>
									{l.trim()}
								</span>
							))}
						</div>
					)}
					{info.kind === "node" && (
						<p>
							{info.connected?.length ? (
								<>
									Connected to{" "}
									{listOf(
										info.connected.map((id) => (
											<button key={id} type="button" className="text-gold hover:underline" onClick={() => goToMap(id)}>
												map #{id}
											</button>
										)),
									)}
								</>
							) : (
								<span className="text-muted-foreground">No paths to other maps.</span>
							)}
						</p>
					)}
					{node !== null && (
						<div className="flex gap-1.5">
							{/* on your own position it takes it back (an "I'm here" by mistake stayed: user) */}
							{routes.player?.node === node ? (
								<Button size="xs" variant="ghost" onClick={routes.clearPlayer}>
									I'm not here
								</Button>
							) : (
								<Button size="xs" variant="ghost" onClick={() => routes.setPlayer(node)}>
									I'm here
								</Button>
							)}
						</div>
					)}
					<p className="text-muted-foreground">Right-click on the map for more (change a landmark, city type…).</p>
				</div>
			)}
		</div>
	);
}
