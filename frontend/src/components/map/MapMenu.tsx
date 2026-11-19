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

interface Props {
	x: number;
	y: number;
	at: Point;
	hit: ItemInfo | null;
	meta: Meta;
	debug: boolean;
	onClose: () => void;
}

/** The right-click menu: bookmarks, screenshots of the spot, routes, landmark and city edits, debug marks. */
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

	const run = (fn: () => Promise<unknown>) => () => {
		fn().catch((e) => s.showError(e));
	};
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
			<DropdownMenuContent align="start" className="w-60">
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
				{hit?.kind === "landmark" && (
					<>
						<DropdownMenuSeparator />
						<DropdownMenuSub>
							<DropdownMenuSubTrigger>Change to</DropdownMenuSubTrigger>
							<DropdownMenuSubContent>
								{meta.landmark_kinds.map((k) => (
									<DropdownMenuItem key={k} onSelect={run(() => app.setLandmark(hit.x, hit.y, k))}>
										{k === hit.landmark_kind ? `● ${k}` : k}
									</DropdownMenuItem>
								))}
							</DropdownMenuSubContent>
						</DropdownMenuSub>
						{hit.removed ? (
							<DropdownMenuItem onSelect={run(() => app.setLandmark(hit.x, hit.y, hit.landmark_kind ?? "City"))}>
								Restore landmark
							</DropdownMenuItem>
						) : (
							<DropdownMenuItem
								variant="destructive"
								onSelect={() =>
									s.askConfirm({
										title: "Delete landmark",
										text: `Delete this ${hit.title}? (Kept in the atlas: Layers > Removed shows it; right-click it to bring it back.)`,
										yes: "Delete",
										danger: true,
										onYes: run(() => app.setLandmark(hit.x, hit.y, "")),
									})
								}
							>
								Delete landmark
							</DropdownMenuItem>
						)}
						{hit.landmark_kind === "City" && (
							<DropdownMenuSub>
								<DropdownMenuSubTrigger>City type</DropdownMenuSubTrigger>
								<DropdownMenuSubContent>
									{meta.city_types.map((t) => (
										<DropdownMenuItem key={t} onSelect={run(() => app.setCityType(hit.id, t))}>
											{hit.city_type === t ? `● ${t}` : t}
										</DropdownMenuItem>
									))}
									<DropdownMenuSeparator />
									<DropdownMenuItem onSelect={run(() => app.setCityType(hit.id, null))}>
										{hit.city_type ? "Automatic" : "● Automatic"}
									</DropdownMenuItem>
								</DropdownMenuSubContent>
							</DropdownMenuSub>
						)}
					</>
				)}
				{hit?.kind === "node" && (
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
