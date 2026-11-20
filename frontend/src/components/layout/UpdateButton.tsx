import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import type { UpdateStatus } from "@/domain/app/Update";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import { useAppStore } from "@/store/AppStore";
import { cn } from "@/utils/Cn";

/** The pill's words and look (user's mockup: "UP TO DATE" with the version on green, "CHECK UPDATE" on red). */
export function pillOf(u: UpdateStatus | undefined): { label: string; ok: boolean } {
	if (!u) return { label: "Check update", ok: false };
	if (u.state === "checking") return { label: "Checking…", ok: false };
	if (u.state === "downloading") return { label: "Downloading…", ok: false };
	if (u.state === "restarting") return { label: "Restarting…", ok: false };
	if (u.available && u.latest) return { label: `Update to ${u.latest.release}`, ok: false };
	if (u.can && u.latest && u.state !== "error") return { label: "Up to date", ok: true };
	return { label: "Check update", ok: false };
}

/**
 * The program's version in the top bar, as Path of Building's update corner (user): it says whether this copy is up
 * to date, and a click checks GitHub and opens the update box: the latest release, its notes, Update now (the app
 * downloads it, restarts on it, and this page reloads itself), and the once-a-day check at start.
 */
export function UpdateButton() {
	const app = useAppClient();
	const queryClient = useQueryClient();
	const showError = useAppStore((s) => s.showError);
	const u = useQuery({ queryKey: AppQueryKeys.update, queryFn: () => app.getUpdate() }).data;
	const version = useAppState().data?.version;
	const [open, setOpen] = useState(false);

	// the app came back on another version or release (an update put in place): this page is the old one's, so it
	// reloads
	const now = version && u ? `${version}|${u.release ?? ""}` : "";
	const first = useRef(now);
	useEffect(() => {
		if (!first.current) first.current = now;
		else if (now && now !== first.current) window.location.reload();
	}, [now]);

	const keep = (r: UpdateStatus) => queryClient.setQueryData(AppQueryKeys.update, r);
	const run = (fn: () => Promise<UpdateStatus>) => void fn().then(keep).catch(showError);
	const check = () => run(() => app.checkUpdate());
	const pill = pillOf(u);
	const shown = u?.release ?? u?.program ?? version ?? "";

	return (
		<>
			<button
				type="button"
				className="flex shrink-0 items-center overflow-hidden rounded-full border text-xs font-semibold tracking-wide whitespace-nowrap uppercase"
				title={u?.can === false ? u.why : "Check for an update"}
				onClick={() => {
					setOpen(true);
					if (u?.can && !u.available && u.state !== "checking") check();
				}}
			>
				<span className="bg-muted px-2 py-0.5 text-foreground">{pill.label}</span>
				<span
					className={cn("rounded-full px-2 py-0.5 tabular-nums", pill.ok ? "bg-lime-400 text-black" : "text-red-400")}
				>
					{shown}
				</span>
			</button>
			{open && u && <UpdateBox u={u} onClose={() => setOpen(false)} onCheck={check} run={run} />}
		</>
	);
}

function UpdateBox({
	u,
	onClose,
	onCheck,
	run,
}: {
	u: UpdateStatus;
	onClose: () => void;
	onCheck: () => void;
	run: (fn: () => Promise<UpdateStatus>) => void;
}) {
	const app = useAppClient();
	const busy = u.state === "checking" || u.state === "downloading" || u.state === "restarting";
	const mb = (n: number) => `${(n / 1e6).toFixed(1)} MB`;
	return (
		<Dialog open onOpenChange={(o) => !o && onClose()}>
			<DialogContent className="sm:max-w-lg">
				<DialogHeader>
					<DialogTitle>Update</DialogTitle>
				</DialogHeader>
				<div className="flex flex-col gap-2 text-sm">
					<p>
						This copy: {u.release ? `release ${u.release}` : "a development copy"} (program v{u.program})
					</p>
					{!u.can && <p className="text-muted-foreground">{u.why}</p>}
					{u.state === "checking" && <p className="text-muted-foreground">Asking GitHub for the latest release…</p>}
					{u.state === "error" && u.error && <p className="text-destructive">{u.error}</p>}
					{u.can && u.latest && !u.available && u.state === "idle" && (
						<p className="text-lime-400">You have the latest release ({u.latest.name}).</p>
					)}
					{u.available && u.latest && (
						<>
							<p className="font-medium text-gold">{u.latest.name} is out.</p>
							{u.latest.notes && (
								<pre className="max-h-64 overflow-y-auto rounded border bg-muted/40 p-2 font-sans text-xs whitespace-pre-wrap">
									{u.latest.notes}
								</pre>
							)}
							{u.latest.url && (
								<a className="text-xs text-gold hover:underline" href={u.latest.url} target="_blank" rel="noreferrer">
									The release on GitHub
								</a>
							)}
						</>
					)}
					{u.state === "downloading" && (
						<p>
							Downloading… {mb(u.got)}
							{u.size ? ` of ${mb(u.size)}` : ""}
						</p>
					)}
					{u.state === "restarting" && (
						<p className="text-gold">Putting the update in place: the app restarts, and this page reloads by itself.</p>
					)}
					{u.just && (
						<p className={u.just.ok ? "text-lime-400" : "text-destructive"}>
							{u.just.ok
								? `Updated from release ${u.just.from} to ${u.just.to}.`
								: `The update to ${u.just.to} failed, nothing changed: ${u.just.error}`}
						</p>
					)}
					{u.can && (
						<div className="mt-1 flex items-center gap-2">
							<Switch
								id="update-auto"
								checked={u.auto}
								onCheckedChange={(on) => run(() => app.setUpdateAuto(on === true))}
							/>
							<Label htmlFor="update-auto" className="font-normal">
								Check for an update when the app starts (once a day)
							</Label>
						</div>
					)}
				</div>
				<DialogFooter>
					{u.can && (
						<Button variant="outline" disabled={busy} onClick={onCheck}>
							Check again
						</Button>
					)}
					{u.available && (
						<Button disabled={busy} onClick={() => run(() => app.installUpdate())}>
							Update now
						</Button>
					)}
					<Button variant="ghost" onClick={onClose}>
						Close
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
