import {
	ChevronDownIcon,
	ChevronRightIcon,
	EyeIcon,
	EyeOffIcon,
	PencilIcon,
	RouteIcon,
	Trash2Icon,
} from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import type { Bookmark, SavedRoute } from "@/domain/bookmarks/Bookmarks";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useBookmarks } from "@/hooks/bookmarks/UseBookmarks";
import { routeBox, routeTitle } from "@/hooks/map/UseRoutes";
import { useAppStoreCalm } from "@/store/AppStore";
import { cn } from "@/utils/Cn";
import { plural } from "@/utils/Format";
import { SavedRouteMenu } from "./SavedRouteMenu";

/** Bookmarks by group: show / hide on the map, go to, edit, move, delete; groups made, renamed, hidden. */
export function BookmarksTab() {
	const app = useAppClient();
	const bookmarks = useBookmarks();
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

	return (
		// anything else done here ends "Add bookmark" (user: it stayed on after editing and deleting bookmarks, and the
		// next click on the map added one instead of selecting)
		<div
			className="flex flex-col gap-3"
			onClickCapture={(e) => {
				if (adding && !(e.target as HTMLElement).closest("[data-add-bookmark]")) s.setMode({ kind: "normal" });
			}}
		>
			<div className="flex flex-wrap gap-1.5">
				<Button
					size="xs"
					data-add-bookmark
					variant={adding ? "outline" : "default"}
					onClick={() => s.setMode(adding ? { kind: "normal" } : { kind: "bookmark" })}
				>
					{adding ? "Cancel adding" : "Add bookmark"}
				</Button>
				<Button
					size="xs"
					variant="outline"
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
			{adding && <p className="text-xs text-gold">Click a map, or a spot, for the new bookmark (Esc cancels).</p>}
			{!groups.length && (
				<p className="text-muted-foreground">No bookmarks yet. Right-click the map, or Add bookmark.</p>
			)}
			{groups.length > 0 && (
				<div className="flex gap-1.5">
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
						variant="ghost"
						onClick={() => {
							for (const g of groups) s.foldGroup(g.name, false);
						}}
					>
						Open all
					</Button>
					<Button
						size="xs"
						variant="ghost"
						onClick={() => {
							for (const g of groups) s.foldGroup(g.name, true);
						}}
					>
						Fold all
					</Button>
				</div>
			)}
			{groups.map((g) => {
				const folded = s.foldedGroups.includes(g.name);
				return (
					<div key={g.name} className="flex flex-col">
						<div className="flex items-center gap-1.5 border-b py-1">
							<Checkbox
								checked={g.items.length ? g.items.every((b) => picked.has(b.id)) : pickedGroups.has(g.name)}
								onCheckedChange={(v) => toggleGroupPick(g.name, v === true)}
								aria-label={`Pick group ${g.name}`}
							/>
							<button
								type="button"
								aria-label={folded ? `Open ${g.name}` : `Fold ${g.name}`}
								aria-expanded={!folded}
								onClick={() => s.foldGroup(g.name, !folded)}
							>
								{folded ? <ChevronRightIcon className="size-4" /> : <ChevronDownIcon className="size-4" />}
							</button>
							{/* a group holding routes: the path symbol before its eye too (user); the others keep the room */}
							{g.items.some((b) => b.route) ? (
								<RouteIcon className="size-4 shrink-0 text-gold" aria-label="Routes" />
							) : (
								<span className="size-4 shrink-0" />
							)}
							<button
								type="button"
								aria-label={g.hidden ? `Show ${g.name}` : `Hide ${g.name}`}
								onClick={() => void app.toggleGroup(g.name).catch(fail)}
							>
								{g.hidden ? <EyeOffIcon className="size-4 text-muted-foreground" /> : <EyeIcon className="size-4" />}
							</button>
							<button
								type="button"
								className={
									g.hidden ? "flex-1 text-left font-semibold text-muted-foreground" : "flex-1 text-left font-semibold"
								}
								onClick={() => s.foldGroup(g.name, !folded)}
							>
								{g.name} <span className="font-normal text-muted-foreground">({g.items.length})</span>
							</button>
							<button
								type="button"
								aria-label={`Rename ${g.name}`}
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
								<PencilIcon className="size-3.5 text-muted-foreground" />
							</button>
						</div>
						{!folded &&
							g.items.map((b) => (
								<div key={b.id} className="flex items-center gap-1.5 py-0.5 pl-1">
									<Checkbox
										checked={picked.has(b.id)}
										onCheckedChange={(v) => toggle(b.id, v === true)}
										aria-label={`Pick ${b.name}`}
									/>
									{/* a saved route: a path symbol before its eye, to tell it from a map's bookmark (user); the
									    others keep the room, so the eyes line up */}
									{b.route ? (
										<RouteIcon className="size-3.5 shrink-0 text-gold" aria-label="Route" />
									) : (
										<span className="size-3.5 shrink-0" />
									)}
									<button
										type="button"
										aria-label={b.hidden ? `Show ${b.name}` : `Hide ${b.name}`}
										onClick={() => void app.toggleBookmark(b.id).catch(fail)}
									>
										{b.shown ? (
											<EyeIcon className="size-3.5" />
										) : (
											<EyeOffIcon className="size-3.5 text-muted-foreground" />
										)}
									</button>
									<button
										type="button"
										className={cn(
											"flex-1 truncate text-left hover:text-gold",
											b.route && s.routeLit === b.id && "text-gold",
										)}
										title={b.note || (b.route ? routeTitle(b.name, b.route) : b.name)}
										onContextMenu={(e) => {
											// a route's menu: track it, add maps, remove maps (user)
											const route = b.route;
											if (!route) return;
											e.preventDefault();
											setRouteMenu({ x: e.clientX, y: e.clientY, bookmark: { ...b, route } });
										}}
										onClick={async () => {
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
										}}
									>
										{b.route ? routeTitle(b.name, b.route) : b.name}
									</button>
									<button
										type="button"
										aria-label={`Edit ${b.name}`}
										onClick={() =>
											s.editBookmark({ id: b.id, x: b.x, y: b.y, name: b.name, group: g.name, note: b.note })
										}
									>
										<PencilIcon className="size-3.5 text-muted-foreground" />
									</button>
									{/* one at a time, without ticking it first (user: deleting needed the box or the pin) */}
									<button type="button" aria-label={`Delete ${b.name}`} onClick={() => remove([b.id], b.name)}>
										<Trash2Icon className="size-3.5 text-muted-foreground hover:text-destructive" />
									</button>
								</div>
							))}
					</div>
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
