import { useQueryClient } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuSeparator,
	DropdownMenuSub,
	DropdownMenuSubContent,
	DropdownMenuSubTrigger,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Meta } from "@/domain/app/Meta";
import type { ItemInfo } from "@/domain/map/ItemInfo";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useDebugMarks } from "@/hooks/debug/UseDebugMarks";
import { useRoutes } from "@/hooks/map/UseRoutes";
import { bookmarkOf, newBookmark } from "@/logic/BookmarkOf";
import type { Point } from "@/logic/Geo";
import { useAppStoreCalm } from "@/store/AppStore";
import { deleteMapText } from "./SelectionBox";

interface Props {
	x: number;
	y: number;
	at: Point;
	hit: ItemInfo | null;
	meta: Meta;
	debug: boolean;
	onClose: () => void;
}

/** The right-click menu: bookmarks, screenshots of the spot, routes, maps deleted or added, landmark and city edits,
 * debug marks. */
export function MapMenu({ x, y, at, hit, meta, debug, onClose }: Props) {
	const app = useAppClient();
	const queryClient = useQueryClient();
	const s = useAppStoreCalm();
	const routes = useRoutes();
	const node = hit?.kind === "node" ? hit.id : (hit?.node ?? null);
	const reasons: Record<string, string[]> = useDebugMarks(debug).data?.reasons ?? {};
	// the bookmark this is, or the one on this map (user: a bookmarked map offered to bookmark it again, and had no
	// way to remove it)
	const mark = bookmarkOf(hit);
	// the landmark this is, or the one on this map: a click on a landmark selects its map, whose menu could only
	// make it a landmark, never back (user: false Cities that couldn't be made normal maps)
	const lm = hit?.kind === "landmark" ? hit : (hit?.on_landmark ?? null);
	const removed = hit?.kind === "landmark" && !!hit.removed;
	const deleteLandmark = (what: string) =>
		lm &&
		s.askConfirm({
			title: what,
			text: `Make this ${lm.title} a normal map? (Kept in the atlas: Layers > Removed shows it; right-click it to bring it back.)`,
			yes: "Normal map",
			danger: true,
			onYes: run(() => app.setLandmark(lm.x, lm.y, "")),
		});

	const run = (fn: () => Promise<unknown>) => () => {
		fn().catch((e) => s.showError(e));
	};
	// a map deleted by hand (user: ghost maps from detection could not be taken away); its landmark goes with it
	const deleteMap = () =>
		hit?.kind === "node" &&
		s.askConfirm({
			title: "Delete map",
			text: deleteMapText(hit),
			yes: "Delete map",
			danger: true,
			onYes: run(() => app.editMap(hit.x, hit.y, "remove")),
		});
	// a map added by hand where the detector missed one (user), plain or with a landmark on it
	const addKinds = ["Map", ...meta.landmark_kinds.filter((k) => k !== "Locked stronghold")];
	const withNote = (title: string, fn: (note: string) => Promise<unknown>) => () =>
		s.ask({
			title: "Debug mark",
			label: `${title} - note (optional)`,
			value: "",
			onOk: (note) => void fn(note).catch(s.showError),
		});
	const refreshDebug = () => queryClient.invalidateQueries({ queryKey: AppQueryKeys.debug });

	return (
		<DropdownMenu open onOpenChange={(open) => !open && onClose()}>
			<DropdownMenuTrigger asChild>
				<span className="pointer-events-none absolute size-px" style={{ left: x, top: y }} />
			</DropdownMenuTrigger>
			<DropdownMenuContent
				align="start"
				className="w-60"
				// what was chosen goes in the log (user: I'm here and Route here left no line of their own); submenus
				// open, they aren't a choice
				onClickCapture={(e) => {
					const item = (e.target as HTMLElement).closest("[role=menuitem]");
					if (!item || item.hasAttribute("aria-haspopup")) return;
					const on = hit ? hit.title : `the spot (${Math.round(at[0])}, ${Math.round(at[1])})`;
					app.log([`Right-click menu on ${on}: ${item.textContent?.replace(/^● /, "")}`]).catch(() => {});
				}}
			>
				{mark ? (
					<>
						<DropdownMenuItem onSelect={() => s.editBookmark(mark)}>Edit bookmark…</DropdownMenuItem>
						<DropdownMenuItem
							variant="destructive"
							onSelect={() =>
								s.askConfirm({
									title: "Remove bookmark",
									text: `Remove the bookmark "${mark.name}"?`,
									yes: "Remove",
									danger: true,
									onYes: run(() => app.deleteBookmarks([mark.id as number])),
								})
							}
						>
							Remove bookmark
						</DropdownMenuItem>
					</>
				) : hit && hit.kind !== "path" ? (
					<DropdownMenuItem onSelect={() => s.editBookmark(newBookmark(hit, at))}>Bookmark this…</DropdownMenuItem>
				) : (
					<DropdownMenuItem onSelect={() => s.editBookmark(newBookmark(null, at))}>Add bookmark here…</DropdownMenuItem>
				)}
				<DropdownMenuItem onSelect={() => s.showSources(at)}>Screenshots of this spot</DropdownMenuItem>
				{node !== null && (
					<>
						<DropdownMenuSeparator />
						{routes.player?.node === node ? (
							<DropdownMenuItem onSelect={routes.clearPlayer}>I'm not here</DropdownMenuItem>
						) : (
							<DropdownMenuItem onSelect={() => routes.setPlayer(node)}>I'm here</DropdownMenuItem>
						)}
						<DropdownMenuItem onSelect={() => routes.routeTo(node)}>Route here</DropdownMenuItem>
					</>
				)}
				{lm && (
					<>
						<DropdownMenuSeparator />
						<DropdownMenuSub>
							<DropdownMenuSubTrigger>{hit?.kind === "node" ? "This map is a…" : "Change to"}</DropdownMenuSubTrigger>
							<DropdownMenuSubContent>
								{meta.landmark_kinds.map((k) => (
									<DropdownMenuItem key={k} onSelect={run(() => app.setLandmark(lm.x, lm.y, k))}>
										{k === lm.landmark_kind && !removed ? `● ${k}` : k}
									</DropdownMenuItem>
								))}
								{!removed && (
									<>
										<DropdownMenuSeparator />
										<DropdownMenuItem onSelect={() => deleteLandmark("Normal map")}>Normal map</DropdownMenuItem>
									</>
								)}
							</DropdownMenuSubContent>
						</DropdownMenuSub>
						{removed ? (
							<DropdownMenuItem onSelect={run(() => app.setLandmark(lm.x, lm.y, lm.landmark_kind ?? "City"))}>
								Restore landmark
							</DropdownMenuItem>
						) : (
							<DropdownMenuItem variant="destructive" onSelect={() => deleteLandmark("Delete landmark")}>
								Delete landmark
							</DropdownMenuItem>
						)}
						{lm.landmark_kind === "City" && !removed && (
							<DropdownMenuSub>
								<DropdownMenuSubTrigger>City type</DropdownMenuSubTrigger>
								<DropdownMenuSubContent>
									{meta.city_types.map((t) => (
										<DropdownMenuItem key={t} onSelect={run(() => app.setCityType(lm.id, t))}>
											{lm.city_type === t ? `● ${t}` : t}
										</DropdownMenuItem>
									))}
									<DropdownMenuSeparator />
									<DropdownMenuItem onSelect={run(() => app.setCityType(lm.id, null))}>
										{lm.city_type ? "Automatic" : "● Automatic"}
									</DropdownMenuItem>
								</DropdownMenuSubContent>
							</DropdownMenuSub>
						)}
					</>
				)}
				{hit?.kind === "node" && !hit.removed && (
					<>
						<DropdownMenuSeparator />
						<DropdownMenuItem variant="destructive" onSelect={deleteMap}>
							Delete map
						</DropdownMenuItem>
					</>
				)}
				{/* on empty ground or a path only: an icon, a pin or a landmark stand on a map (refused: self review) */}
				{(!hit || hit.kind === "path") && (
					<>
						<DropdownMenuSeparator />
						<DropdownMenuSub>
							<DropdownMenuSubTrigger>Add here</DropdownMenuSubTrigger>
							<DropdownMenuSubContent>
								{addKinds.map((k) => (
									<DropdownMenuItem
										key={k}
										onSelect={run(() => app.editMap(at[0], at[1], "add", k === "Map" ? "" : k))}
									>
										{k}
									</DropdownMenuItem>
								))}
							</DropdownMenuSubContent>
						</DropdownMenuSub>
					</>
				)}
				{hit?.kind === "node" && !lm && (
					<>
						<DropdownMenuSeparator />
						<DropdownMenuSub>
							<DropdownMenuSubTrigger>This map is a…</DropdownMenuSubTrigger>
							<DropdownMenuSubContent>
								{meta.landmark_kinds.map((k) => (
									<DropdownMenuItem key={k} onSelect={run(() => app.setLandmark(hit.x, hit.y, k, "map"))}>
										{k}
									</DropdownMenuItem>
								))}
							</DropdownMenuSubContent>
						</DropdownMenuSub>
					</>
				)}
				{debug && (
					<>
						<DropdownMenuSeparator />
						<DropdownMenuSub>
							<DropdownMenuSubTrigger>Debug</DropdownMenuSubTrigger>
							<DropdownMenuSubContent className="w-72">
								{node !== null && (
									<>
										{(reasons["wrong map"] ?? []).map((r) => (
											<DropdownMenuItem
												key={r}
												onSelect={withNote(`Map: ${r}`, async (note) => {
													await app.addDebugMark({ kind: "wrong map", reason: r, note, maps: [node] });
													await refreshDebug();
												})}
											>
												Map: {r}…
											</DropdownMenuItem>
										))}
										<DropdownMenuItem
											onSelect={withNote("Missing path from here", async (note) =>
												s.setMode({ kind: "debug-link", from: node, note }),
											)}
										>
											Missing path from here: click the other map
										</DropdownMenuItem>
										<DropdownMenuSeparator />
									</>
								)}
								{hit?.kind === "path" &&
									(reasons["wrong path"] ?? []).map((r) => (
										<DropdownMenuItem
											key={r}
											onSelect={withNote(`Path: ${r}`, async (note) => {
												await app.addDebugMark({ kind: "wrong path", reason: r, note, path: hit.id });
												await refreshDebug();
											})}
										>
											Path: {r}…
										</DropdownMenuItem>
									))}
								{(reasons["missing map"] ?? []).map((r) => (
									<DropdownMenuItem
										key={r}
										onSelect={withNote(`Add a map here: ${r}`, async (note) => {
											await app.addDebugMark({ kind: "missing map", reason: r, note, x: at[0], y: at[1] });
											await refreshDebug();
										})}
									>
										Add a map here: {r}…
									</DropdownMenuItem>
								))}
							</DropdownMenuSubContent>
						</DropdownMenuSub>
					</>
				)}
			</DropdownMenuContent>
		</DropdownMenu>
	);
}
