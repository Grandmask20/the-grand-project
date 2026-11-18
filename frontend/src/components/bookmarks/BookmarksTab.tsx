import { ChevronDownIcon, ChevronRightIcon, EyeIcon, EyeOffIcon, PencilIcon } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useBookmarks } from "@/hooks/bookmarks/UseBookmarks";
import { useAppStoreCalm } from "@/store/AppStore";
import { plural } from "@/utils/Format";

/** Bookmarks by group: show / hide on the map, go to, edit, move, delete; groups made, renamed, hidden. */
export function BookmarksTab() {
	const app = useAppClient();
	const bookmarks = useBookmarks();
	const [picked, setPicked] = useState<Set<number>>(new Set());
	const s = useAppStoreCalm();
	const groups = bookmarks.data?.groups ?? [];
	const fail = (e: unknown) => s.showError(e);
	const ids = [...picked];

	const toggle = (id: number, on: boolean) => {
		const next = new Set(picked);
		if (on) next.add(id);
		else next.delete(id);
		setPicked(next);
	};

	return (
		<div className="flex flex-col gap-3">
			<div className="flex flex-wrap gap-1.5">
				<Button size="xs" onClick={() => s.setMode({ kind: "bookmark" })}>
					Add bookmark
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
							options: groups.map((g) => g.name),
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
					disabled={!ids.length}
					onClick={() =>
						s.askConfirm({
							title: "Delete bookmarks",
							text: `Delete ${plural(ids.length, "bookmark")}?`,
							yes: "Delete",
							danger: true,
							onYes: () =>
								void app
									.deleteBookmarks(ids)
									.then(() => setPicked(new Set()))
									.catch(fail),
						})
					}
				>
					Delete
				</Button>
			</div>
			{s.mode.kind === "bookmark" && (
				<p className="text-xs text-gold">Click on the map where the bookmark goes (Esc cancels).</p>
			)}
			{!groups.length && (
				<p className="text-muted-foreground">No bookmarks yet. Right-click the map, or Add bookmark.</p>
			)}
			{groups.length > 1 && (
				<div className="flex gap-1.5">
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
							<button
								type="button"
								aria-label={folded ? `Open ${g.name}` : `Fold ${g.name}`}
								aria-expanded={!folded}
								onClick={() => s.foldGroup(g.name, !folded)}
							>
								{folded ? <ChevronRightIcon className="size-4" /> : <ChevronDownIcon className="size-4" />}
							</button>
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
										onOk: (n) => void app.renameGroup(g.name, n).catch(fail),
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
										className="flex-1 truncate text-left hover:text-gold"
										title={b.note || b.name}
										onClick={async () => {
											s.flyTo(b.x, b.y, 1);
											try {
												await s.selectLoaded(app.getInfo("bookmark", b.id));
											} catch (e) {
												fail(e);
											}
										}}
									>
										{b.name}
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
								</div>
							))}
					</div>
				);
			})}
		</div>
	);
}
