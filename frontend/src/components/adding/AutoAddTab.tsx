import { useQueryClient } from "@tanstack/react-query";
import { CheckIcon, ImageIcon, MoveIcon, RotateCwIcon } from "lucide-react";
import type { ReactNode } from "react";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import { useAtlasActions } from "@/hooks/atlas/UseAtlasActions";
import { useAppStoreCalm } from "@/store/AppStore";

const link = "text-xs text-gold hover:underline disabled:text-muted-foreground disabled:no-underline";

/** A heading of the page, with its links on the right. */
function Heading({ title, children }: { title: string; children?: ReactNode }) {
	return (
		<div className="flex items-center justify-between gap-3 border-b pb-1">
			<h3 className="text-xs font-semibold tracking-wide text-gold uppercase">{title}</h3>
			<div className="flex gap-3">{children}</div>
		</div>
	);
}

/** Auto-add (PO's canvas): the watched folder, the screenshots waiting for a place (each placed by hand or tried
 * again on its row), and those added in this session (a click goes there). */
export function AutoAddTab() {
	const app = useAppClient();
	const queryClient = useQueryClient();
	const state = useAppState().data;
	const actions = useAtlasActions();
	const s = useAppStoreCalm();
	if (!state) return null;
	const fail = (e: unknown) => s.showError(e);
	const refresh = () => queryClient.invalidateQueries({ queryKey: AppQueryKeys.state });
	const w = state.watch;

	return (
		<div className="flex flex-col gap-5">
			<div className="flex flex-col gap-1.5">
				<Label className="text-sm font-medium">
					<Switch
						checked={w.on}
						disabled={!state.atlas}
						onCheckedChange={(on) => void app.setWatch(on).then(refresh).catch(fail)}
						aria-label="Add new screenshots automatically"
					/>
					Add new screenshots automatically
				</Label>
				<p className="text-xs break-all text-muted-foreground">
					{w.folder
						? `${w.picked ? "watching: " : "watching this atlas's folder: "}${w.folder}`
						: "open an atlas first"}
				</p>
				<div className="flex gap-3">
					<button
						type="button"
						className={link}
						disabled={!state.atlas}
						onClick={() =>
							s.pickFiles({
								title: "Folder your screenshots are saved to",
								folders: true,
								start: w.folder,
								onPick: ([f]) => f && void app.setWatchFolder(f).then(refresh).catch(fail),
							})
						}
					>
						Watch another folder…
					</button>
					{w.picked && (
						<button
							type="button"
							className={link}
							onClick={() => void app.setWatchFolder(null).then(refresh).catch(fail)}
						>
							Atlas folder
						</button>
					)}
				</div>
				<p className="text-xs text-muted-foreground">
					Set Steam to save screenshots in this folder while you map: each new one is added. One that might be wrong is
					shown on the map before it is added.
				</p>
			</div>

			{s.mode.kind === "ghost" && (
				<p className="text-xs text-gold">
					{s.mode.ghost.name}: drag it roughly where it belongs, then press Enter or double-click (Esc cancels).
				</p>
			)}

			<section className="flex flex-col gap-1">
				<Heading title={`Waiting for a place · ${state.waiting.length}`}>
					{state.waiting.length > 0 && (
						<button type="button" className={link} onClick={() => void app.retryWaiting(null).catch(fail)}>
							Retry all
						</button>
					)}
				</Heading>
				{!state.waiting.length && <p className="py-1 text-sm text-muted-foreground">No screenshot is waiting.</p>}
				<ul className="flex flex-col gap-1">
					{state.waiting.map((wt, k) => (
						<li key={wt.path} className="flex items-center gap-2 rounded-md bg-card px-2 py-1.5">
							<ImageIcon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
							<span className="flex min-w-0 flex-1 flex-col">
								<span className="truncate text-sm">{wt.name}</span>
								<span className="text-xs text-muted-foreground">
									{wt.tries ? `waiting, tried ${wt.tries}x` : "queued"}
								</span>
							</span>
							<button
								type="button"
								aria-label={`Retry ${wt.name}`}
								title="Try again"
								className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
								onClick={() => void app.retryWaiting([k]).catch(fail)}
							>
								<RotateCwIcon className="size-3.5" />
							</button>
							<button
								type="button"
								aria-label={`Place ${wt.name} by hand`}
								className="flex h-7 items-center gap-1.5 rounded border px-2 text-xs whitespace-nowrap hover:bg-accent"
								onClick={() =>
									void app
										.takeWaiting(k)
										.then(({ path }) => actions.startGhost(path))
										.catch(fail)
								}
							>
								<MoveIcon className="size-3.5" aria-hidden />
								Place by hand
							</button>
						</li>
					))}
				</ul>
			</section>

			<section className="flex flex-col gap-1">
				<Heading title="Added this session">
					<button type="button" className={link} disabled={!state.undo.length || state.busy} onClick={askUndo}>
						Undo last add
					</button>
				</Heading>
				{!state.recent.length && (
					<p className="py-1 text-sm text-muted-foreground">Nothing added in this session yet.</p>
				)}
				<ul className="flex max-h-72 flex-col overflow-y-auto">
					{state.recent.map((name, k) => (
						<li key={name}>
							<button
								type="button"
								className="flex min-h-8 w-full items-center gap-2 rounded px-1 text-left text-sm hover:bg-accent"
								onClick={() =>
									void app
										.gotoRecent(name)
										.then(({ centre }) => s.flyTo(centre[0], centre[1], 0.25))
										.catch(fail)
								}
							>
								<CheckIcon className="size-3.5 shrink-0 text-green-400" aria-hidden />
								<span className="flex-1 truncate">{name}</span>
								{k === 0 && <span className="text-[10px] font-semibold text-gold">NEWEST</span>}
							</button>
						</li>
					))}
				</ul>
			</section>
		</div>
	);

	function askUndo() {
		const names = state?.undo.at(-1) ?? [];
		s.askConfirm({
			title: "Undo last add",
			text: `Remove the screenshot(s) added last?\n\n${names.join("\n")}`,
			yes: "Undo",
			onYes: () => void app.undo().catch(fail),
		});
	}
}
