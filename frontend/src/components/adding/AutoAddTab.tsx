import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { Section } from "@/components/common/Section";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import { useAtlasActions } from "@/hooks/atlas/UseAtlasActions";
import { useAppStore } from "@/store/AppStore";
import { plural } from "@/utils/Format";

/** Auto-add (the watched folder), the screenshots added lately and those waiting for a place. */
export function AutoAddTab() {
	const app = useAppClient();
	const queryClient = useQueryClient();
	const state = useAppState().data;
	const actions = useAtlasActions();
	const s = useAppStore();
	const [waitPick, setWaitPick] = useState<number | null>(null);
	if (!state) return null;
	const fail = (e: unknown) => s.showError(e);
	const refresh = () => queryClient.invalidateQueries({ queryKey: AppQueryKeys.state });
	const w = state.watch;

	return (
		<div className="flex flex-col gap-5">
			<Section title="Auto-add">
				<Label className="font-normal">
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
				<p className="text-xs text-muted-foreground">
					Set Steam to save screenshots in this folder while you map: each new one is added. One that might be wrong is
					shown on the map before it is added.
				</p>
				<div className="flex flex-wrap gap-1.5">
					<Button
						size="xs"
						variant="outline"
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
					</Button>
					{w.picked && (
						<Button size="xs" variant="outline" onClick={() => void app.setWatchFolder(null).then(refresh).catch(fail)}>
							Atlas folder
						</Button>
					)}
				</div>
			</Section>

			{s.mode.kind === "ghost" && (
				<div className="rounded border border-gold/60 p-2 text-xs text-gold">
					{s.mode.ghost.name}: drag it roughly where it belongs, then press Enter or double-click (Esc cancels).
				</div>
			)}

			<Section
				title="Recently added"
				actions={
					<Button size="xs" variant="outline" disabled={!state.undo.length || state.busy} onClick={() => askUndo()}>
						Undo last add
					</Button>
				}
			>
				{!state.recent.length && <p className="text-muted-foreground">Nothing added in this session yet.</p>}
				<ul className="max-h-56 overflow-y-auto rounded border font-mono text-xs">
					{state.recent.map((name, k) => (
						<li key={name}>
							<button
								type="button"
								className="w-full truncate px-2 py-0.5 text-left hover:bg-accent"
								onClick={() =>
									void app
										.gotoRecent(name)
										.then(({ centre }) => s.flyTo(centre[0], centre[1], 0.25))
										.catch(fail)
								}
							>
								{k === 0 ? "NEWEST  " : `${String(k).padStart(4)}    `}
								{name}
							</button>
						</li>
					))}
				</ul>
			</Section>

			<Section title="Waiting for a place">
				{!state.waiting.length ? (
					<p className="text-muted-foreground">No screenshot is waiting.</p>
				) : (
					<>
						<ul className="max-h-48 overflow-y-auto rounded border text-xs">
							{state.waiting.map((wt, k) => (
								<li key={wt.path}>
									<button
										type="button"
										className={`w-full truncate px-2 py-0.5 text-left hover:bg-accent ${waitPick === k ? "bg-accent" : ""}`}
										onClick={() => setWaitPick(k)}
									>
										{wt.name}{" "}
										<span className="text-muted-foreground">
											- {wt.tries ? `waiting, tried ${wt.tries}x` : "queued"}
										</span>
									</button>
								</li>
							))}
						</ul>
						<div className="flex flex-wrap gap-1.5">
							<Button
								size="xs"
								variant="outline"
								disabled={waitPick === null}
								onClick={() => void app.retryWaiting(waitPick === null ? null : [waitPick]).catch(fail)}
							>
								Retry
							</Button>
							<Button size="xs" variant="outline" onClick={() => void app.retryWaiting(null).catch(fail)}>
								Retry all
							</Button>
							<Button
								size="xs"
								variant="outline"
								disabled={waitPick === null}
								onClick={() =>
									waitPick !== null &&
									void app
										.takeWaiting(waitPick)
										.then(({ path }) => {
											setWaitPick(null);
											return actions.startGhost(path);
										})
										.catch(fail)
								}
							>
								Place by hand
							</Button>
						</div>
						<p className="text-xs text-muted-foreground">{plural(state.waiting.length, "screenshot")} waiting.</p>
					</>
				)}
			</Section>
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
