import { useQueryClient } from "@tanstack/react-query";
import {
	BookmarkIcon,
	ChevronDownIcon,
	ChevronRightIcon,
	EllipsisIcon,
	EyeIcon,
	EyeOffIcon,
	PencilIcon,
	PlusIcon,
	RouteIcon,
	Trash2Icon,
} from "lucide-react";
import { type MouseEvent, type ReactNode, useState } from "react";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import type { Bookmark, Bookmarks, SavedRoute } from "@/domain/bookmarks/Bookmarks";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useBookmarks } from "@/hooks/bookmarks/UseBookmarks";
import { routeBox, routeTitle } from "@/hooks/map/UseRoutes";
import { useAppStoreCalm } from "@/store/AppStore";
import { cn } from "@/utils/Cn";
import { plural } from "@/utils/Format";
import { SavedRouteMenu } from "./SavedRouteMenu";

/** A small action of a row: shown when the row is pointed at or in focus (`always`: kept in sight, a hidden eye). */
function RowAction({
	label,
	onClick,
	always = false,
	children,
}: {
	label: string;
	onClick: (e: MouseEvent<HTMLButtonElement>) => void;
	always?: boolean;
	children: ReactNode;
}) {
	return (
		<button
			type="button"
			aria-label={label}
			title={label}
			onClick={onClick}
			className={cn(
				"rounded p-1 text-muted-foreground hover:bg-background hover:text-foreground focus-visible:opacity-100",
				!always && "opacity-0 group-hover/row:opacity-100 group-focus-within/row:opacity-100",
			)}
		>
			{children}
		</button>
	);
}

const link = "flex items-center gap-1 text-gold hover:underline disabled:text-muted-foreground disabled:no-underline";

/**
 * Saved: bookmarks by group, and the saved routes in them (PO's canvas): a click goes there, its row's actions show
 * on it (hide, edit, delete; a route's menu); groups fold, hide, rename. Picking several (to move or delete them) is
 * Select's: the tick boxes show only then.
 */
export function BookmarksTab() {
	const app = useAppClient();
	const bookmarks = useBookmarks();
	const [selecting, setSelecting] = useState(false);
	const [picked, setPicked] = useState<Set<number>>(new Set());
	// groups ticked: all their bookmarks are picked, and an empty one is deleted with Delete (user: no way to delete
	// an empty group)
	const [pickedGroups, setPickedGroups] = useState<Set<string>>(new Set());
	const s = useAppStoreCalm();
	const [routeMenu, setRouteMenu] = useState<{
		x: number;
		y: number;
		bookmark: Bookmark & { route: SavedRoute };
	} | null>(null);
	const groups = bookmarks.data?.groups ?? [];
	const fail = (e: unknown) => s.showError(e);
	// only bookmarks still in the list: a picked one deleted meanwhile (by another step, or a group delete that failed
	// after its bookmarks went) doesn't count (CodeRabbit)
	const listed = new Set(groups.flatMap((g) => g.items.map((b) => b.id)));
	const ids = [...picked].filter((id) => listed.has(id));

	const toggle = (id: number, on: boolean) => {
		const next = new Set(picked);
		if (on) next.add(id);
		else next.delete(id);
		setPicked(next);
	};
	const toggleGroupPick = (name: string, on: boolean) => {
		const g = groups.find((x) => x.name === name);
		const next = new Set(picked);
		for (const b of g?.items ?? []) {
			if (on) next.add(b.id);
			else next.delete(b.id);
		}
		setPicked(next);
		const gs = new Set(pickedGroups);
		if (on) gs.add(name);
		else gs.delete(name);
		setPickedGroups(gs);
	};
	const allIds = groups.flatMap((g) => g.items.map((b) => b.id));
	// every bookmark and every empty group picked, as the group tick boxes count them (with only empty groups, Select
	// all never turned into Select none: CodeRabbit)
	const everything =
		groups.length > 0 &&
		allIds.every((id) => picked.has(id)) &&
		groups.every((g) => g.items.length || pickedGroups.has(g.name));
	const emptyPicked = groups.filter((g) => !g.items.length && pickedGroups.has(g.name)).map((g) => g.name);
	const endSelecting = () => {
		setSelecting(false);
		setPicked(new Set());
		setPickedGroups(new Set());
	};

	// folding: kept per atlas by the app (user: Fold all was forgotten after a reload), shown at once
	const queryClient = useQueryClient();
	const fold = (names: string[], folded: boolean) => {
		queryClient.setQueryData<Bookmarks>(
			AppQueryKeys.bookmarks,
			(d) => d && { groups: d.groups.map((g) => (names.includes(g.name) ? { ...g, folded } : g)) },
		);
		// failed: the groups as the app keeps them (shown folded, they opened again on a reload: CodeRabbit)
		void app.foldGroups(names, folded).catch((e) => {
			fail(e);
			void queryClient.invalidateQueries({ queryKey: AppQueryKeys.bookmarks });
		});
	};
	const anyOpen = groups.some((g) => !g.folded);

	const adding = s.mode.kind === "bookmark";
	const remove = (ids: number[], name?: string, emptyGroups: string[] = []) =>
		s.askConfirm({
			title: "Delete bookmarks",
			text: name
				? `Delete "${name}"?`
				: `Delete ${[
						ids.length ? plural(ids.length, "bookmark") : "",
						emptyGroups.length ? plural(emptyGroups.length, "empty group") : "",
					]
						.filter(Boolean)
						.join(" and ")}?`,
			yes: "Delete",
			danger: true,
			onYes: () =>
				void Promise.all([
					ids.length ? app.deleteBookmarks(ids) : null,
					emptyGroups.length ? app.deleteGroups(emptyGroups) : null,
				])
					.then(() => {
						setPicked((p) => new Set([...p].filter((id) => !ids.includes(id))));
						setPickedGroups((g) => new Set([...g].filter((n) => !emptyGroups.includes(n))));
					})
					.catch(fail),
		});
	const open = async (b: Bookmark) => {
		// a route: lit up as a selected bookmark is, the whole of it in view with room round it (user)
		if (b.route) {
			s.lightRoute(b.id);
			return s.fitArea(routeBox(b.route));
		}
		s.flyTo(b.x, b.y, 1);
		try {
			await s.selectLoaded(app.getInfo("bookmark", b.id));
		} catch (e) {
			fail(e);
		}
	};
	const edit = (b: Bookmark, group: string) =>
		s.editBookmark({ id: b.id, x: b.x, y: b.y, name: b.name, group, note: b.note });

	return (
		// anything else done here ends "Add bookmark" (user: it stayed on after editing and deleting bookmarks, and the
		// next click on the map added one instead of selecting)
		<div
			className="flex flex-col gap-3"
			onClickCapture={(e) => {
				if (adding && !(e.target as HTMLElement).closest("[data-add-bookmark]")) s.setMode({ kind: "normal" });
			}}
		>
			<div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
				<button
					type="button"
					data-add-bookmark
					className={link}
					onClick={() => s.setMode(adding ? { kind: "normal" } : { kind: "bookmark" })}
				>
					{!adding && <PlusIcon className="size-3.5" aria-hidden />}
					{adding ? "Cancel adding" : "Add bookmark"}
				</button>
				<button
					type="button"
					className={link}
					onClick={() =>
						s.ask({
							title: "New group",
							label: "Group name:",
							value: "",
							onOk: (n) => void app.newGroup(n).catch(fail),
						})
					}
				>
					New group
				</button>
				<span className="flex-1" />
				{groups.length > 0 && (
					<>
						<button
							type="button"
							className={link}
							onClick={() =>
								fold(
									groups.map((g) => g.name),
									anyOpen,
								)
							}
						>
							{anyOpen ? "Fold all" : "Open all"}
						</button>
						<button
							type="button"
							className={link}
							aria-pressed={selecting}
							onClick={() => (selecting ? endSelecting() : setSelecting(true))}
						>
							{selecting ? "Done" : "Select"}
						</button>
					</>
				)}
			</div>

			{selecting && (
				<div className="flex flex-wrap items-center gap-1.5 rounded-md border bg-card px-2 py-1.5 text-xs">
					<span className="flex-1 text-muted-foreground">{ids.length + emptyPicked.length} picked</span>
					<Button
						size="xs"
						variant="ghost"
						onClick={() => {
							setPicked(everything ? new Set() : new Set(allIds));
							setPickedGroups(everything ? new Set() : new Set(groups.map((g) => g.name)));
						}}
					>
						{everything ? "Select none" : "Select all"}
					</Button>
					<Button
						size="xs"
						variant="outline"
						disabled={!ids.length}
						onClick={() =>
							s.ask({
								title: "Move bookmarks",
								label: `Move ${plural(ids.length, "bookmark")} to group:`,
								value: "",
								// a dropdown of the groups (user: "moveto needs a dropdown"); New group makes another
								choices: groups.map((g) => g.name),
								onOk: (g) =>
									void app
										.moveBookmarks(ids, g)
										.then(() => setPicked(new Set()))
										.catch(fail),
							})
						}
					>
						Move to…
					</Button>
					<Button
						size="xs"
						variant="destructive"
						disabled={!ids.length && !emptyPicked.length}
						onClick={() => remove(ids, undefined, emptyPicked)}
					>
						Delete
					</Button>
				</div>
			)}

			{!groups.length && (
				<p className="text-sm text-muted-foreground">
					No bookmarks yet: the Bookmark map tool, Add bookmark, or right-click the map.
				</p>
			)}

			{groups.map((g) => {
				const folded = !!g.folded;
				const routes = g.items.some((b) => b.route);
				return (
					<section key={g.name} className="flex flex-col">
						<div className="group/row flex h-9 items-center gap-2 border-b">
							{selecting && (
								<Checkbox
									checked={g.items.length ? g.items.every((b) => picked.has(b.id)) : pickedGroups.has(g.name)}
									onCheckedChange={(v) => toggleGroupPick(g.name, v === true)}
									aria-label={`Pick group ${g.name}`}
								/>
							)}
							<button
								type="button"
								aria-label={folded ? `Open ${g.name}` : `Fold ${g.name}`}
								aria-expanded={!folded}
								onClick={() => fold([g.name], !folded)}
								className="flex min-w-0 flex-1 items-center gap-2 text-left"
							>
								{folded ? (
									<ChevronRightIcon className="size-4 shrink-0 text-muted-foreground" />
								) : (
									<ChevronDownIcon className="size-4 shrink-0 text-muted-foreground" />
								)}
								{/* a group holding routes: the path symbol (user) */}
								{routes && <RouteIcon className="size-4 shrink-0 text-gold" aria-label="Routes" />}
								<span className={cn("truncate text-sm font-semibold", g.hidden && "text-muted-foreground")}>
									{g.name}
								</span>
								<span className="text-xs text-muted-foreground">{g.items.length}</span>
							</button>
							<RowAction
								label={g.hidden ? `Show ${g.name}` : `Hide ${g.name}`}
								always={g.hidden}
								onClick={() => void app.toggleGroup(g.name).catch(fail)}
							>
								{g.hidden ? <EyeOffIcon className="size-4" /> : <EyeIcon className="size-4" />}
							</RowAction>
							<RowAction
								label={`Rename ${g.name}`}
								onClick={() =>
									s.ask({
										title: "Rename group",
										label: "New name:",
										value: g.name,
										onOk: (n) =>
											void app
												.renameGroup(g.name, n)
												// a ticked group stays ticked under its new name (user)
												.then(() =>
													setPickedGroups((gs) =>
														gs.has(g.name) ? new Set([...gs].filter((x) => x !== g.name).concat(n.trim())) : gs,
													),
												)
												.catch(fail),
									})
								}
							>
								<PencilIcon className="size-3.5" />
							</RowAction>
						</div>
						{!folded &&
							g.items.map((b) => {
								const route = b.route;
								const tracking = !!route && s.route?.saved === b.id && s.route.at !== undefined;
								const left = tracking && s.route ? s.route.path.length - 1 - (s.route.at ?? 0) : 0;
								const lit = !!route && s.routeLit === b.id;
								return (
									<div
										key={b.id}
										className={cn(
											"group/row flex items-center gap-2 rounded px-1 hover:bg-accent",
											route ? "py-1.5" : "min-h-9",
											(lit || tracking) && "bg-accent",
										)}
									>
										{selecting && (
											<Checkbox
												checked={picked.has(b.id)}
												onCheckedChange={(v) => toggle(b.id, v === true)}
												aria-label={`Pick ${b.name}`}
											/>
										)}
										{/* a saved route: the path symbol, to tell it from a map's bookmark (user) */}
										{route ? (
											<RouteIcon
												className={cn("size-4 shrink-0", tracking ? "text-route" : "text-gold")}
												aria-label="Route"
											/>
										) : (
											<BookmarkIcon
												className={cn("size-4 shrink-0", b.shown ? "text-gold" : "text-muted-foreground")}
												aria-hidden
											/>
										)}
										<button
											type="button"
											aria-label={route ? routeTitle(b.name, route) : b.name}
											className={cn(
												"flex min-w-0 flex-1 flex-col text-left text-sm",
												!b.shown && "text-muted-foreground",
												lit && "text-gold",
											)}
											title={b.note || (route ? routeTitle(b.name, route) : b.name)}
											onContextMenu={(e) => {
												// a route's menu: track it, add maps, remove maps (user)
												if (!route) return;
												e.preventDefault();
												setRouteMenu({ x: e.clientX, y: e.clientY, bookmark: { ...b, route } });
											}}
											onClick={() => void open(b)}
										>
											<span className="truncate">{b.name}</span>
											{route && (
												<span className="text-xs text-muted-foreground">
													map #{route.from} → map #{route.to} · {plural(route.maps, "map")}
													{tracking && ` · ${left} left`}
												</span>
											)}
											{tracking && s.route && (
												<span className="mt-1 block h-1 rounded bg-border">
													<span
														className="block h-1 rounded bg-route"
														style={{ width: `${(100 * (s.route.at ?? 0)) / Math.max(1, s.route.path.length - 1)}%` }}
													/>
												</span>
											)}
										</button>
										<RowAction
											label={b.hidden ? `Show ${b.name}` : `Hide ${b.name}`}
											always={!b.shown}
											onClick={() => void app.toggleBookmark(b.id).catch(fail)}
										>
											{b.shown ? <EyeIcon className="size-3.5" /> : <EyeOffIcon className="size-3.5" />}
										</RowAction>
										<RowAction label={`Edit ${b.name}`} onClick={() => edit(b, g.name)}>
											<PencilIcon className="size-3.5" />
										</RowAction>
										{/* one at a time, without ticking it first (user: deleting needed the box or the pin) */}
										<RowAction label={`Delete ${b.name}`} onClick={() => remove([b.id], b.name)}>
											<Trash2Icon className="size-3.5" />
										</RowAction>
										{route && (
											<RowAction
												label={`Route menu: ${b.name}`}
												always
												onClick={(e) => {
													const r = e.currentTarget.getBoundingClientRect();
													setRouteMenu({ x: r.left, y: r.bottom, bookmark: { ...b, route } });
												}}
											>
												<EllipsisIcon className="size-4" />
											</RowAction>
										)}
									</div>
								);
							})}
					</section>
				);
			})}
			{routeMenu && (
				<SavedRouteMenu
					x={routeMenu.x}
					y={routeMenu.y}
					bookmark={routeMenu.bookmark}
					onClose={() => setRouteMenu(null)}
				/>
			)}
		</div>
	);
}
