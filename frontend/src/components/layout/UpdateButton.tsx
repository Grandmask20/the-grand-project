import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { keepUpdate, newerUpdate } from "@/api/EventStream";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import type { UpdateStatus } from "@/domain/app/Update";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import { type NotesSpan, notesBlocks, notesWithSkipped } from "@/logic/ReleaseNotes";
import { useAppStore } from "@/store/AppStore";
import { cn } from "@/utils/Cn";

/** The pill's words and look (user's mockup: "UP TO DATE" with the version on green, "CHECK UPDATE" on red). */
/** The box checks GitHub: a copy that updates in the app, or the desktop app (which puts the update in place itself). */
const checks = (u: UpdateStatus) => u.can || u.desktop === true;

export function pillOf(u: UpdateStatus | undefined): { label: string; ok: boolean } {
	if (!u) return { label: "Check update", ok: false };
	if (u.state === "checking") return { label: "Checking…", ok: false };
	if (u.state === "downloading") return { label: "Downloading…", ok: false };
	if (u.state === "restarting") return { label: "Restarting…", ok: false };
	if (u.available && u.latest) return { label: `Update to ${u.latest.release}`, ok: false };
	if (checks(u) && u.latest && u.state !== "error") return { label: "Up to date", ok: true };
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
	// a status asked for is kept only when newer than the one the page has (an event may have come meanwhile)
	const u = useQuery({
		queryKey: AppQueryKeys.update,
		queryFn: async () =>
			newerUpdate(queryClient.getQueryData<UpdateStatus>(AppQueryKeys.update), await app.getUpdate()),
	}).data;
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

	const keep = (r: UpdateStatus) => keepUpdate(queryClient, r);
	const run = (fn: () => Promise<UpdateStatus>) => void fn().then(keep).catch(showError);
	const check = () => run(() => app.checkUpdate());
	const pill = pillOf(u);
	const shown = u?.release ?? u?.program ?? version ?? "";

	return (
		<>
			<button
				type="button"
				className="flex shrink-0 items-center overflow-hidden rounded-full border text-xs font-semibold tracking-wide whitespace-nowrap uppercase"
				title={u?.can === false ? u.why : "The update box"}
				onClick={() => setOpen(true)} // (it opens the box; checking is its button's: user)
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
	const notes = u.latest ? notesWithSkipped(u.latest) : "";
	const left = useCountdown(u.next);
	const mb = (n: number) => `${(n / 1e6).toFixed(1)} MB`;
	return (
		<Dialog open onOpenChange={(o) => !o && onClose()}>
			<DialogContent className="sm:max-w-lg">
				<DialogHeader>
					<DialogTitle>Update</DialogTitle>
				</DialogHeader>
				<div className="flex flex-col gap-2 text-sm">
					{/* the release number only (1.3, 1.3.1): the program's own version isn't the players' (user) */}
					<p>This copy: {u.release ? `release ${u.release}` : `a development copy (program v${u.program})`}</p>
					{!u.can && <p className="text-muted-foreground">{u.why}</p>}
					{u.state === "checking" && <p className="text-muted-foreground">Asking GitHub for the latest release…</p>}
					{u.state === "error" && u.error && <p className="text-destructive">{u.error}</p>}
					{checks(u) && u.latest && !u.available && u.state === "idle" && (
						<p className="text-lime-400">You have the latest release ({u.latest.name}).</p>
					)}
					{u.available && u.latest && (
						<>
							<p className="font-medium text-gold">{u.latest.name} is out.</p>
							{notes && <Notes notes={notes} />}
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
					{/* (a done update not under a newer release's notes: "Updated from 1.3 to 1.3.1" beside "1.3.2 is out"
					read oddly; a failed one says why beside the offer it failed on) */}
					{u.just && (!u.just.ok || !u.available) && (
						<p className={u.just.ok ? "text-lime-400" : "text-destructive"}>
							{u.just.ok
								? `Updated from release ${u.just.from} to ${u.just.to}.`
								: `The update to ${u.just.to} failed, nothing changed: ${u.just.error}`}
						</p>
					)}
					{checks(u) && (
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
					{checks(u) && (
						// once a minute at most (GitHub answers 60 checks an hour per address: user, quick clicks)
						<Button variant={u.latest ? "outline" : "default"} disabled={busy || left > 0} onClick={onCheck}>
							{left > 0 ? `Check again in ${left} s` : u.latest ? "Check again" : "Check now"}
						</Button>
					)}
					{u.can && u.available && (
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

/** A release's notes as the box shows them: headings, points and paragraphs (logic/ReleaseNotes; they showed as
 * typed, "##" and all: user). */
function Notes({ notes }: { notes: string }) {
	return (
		<div className="flex max-h-64 flex-col gap-1.5 overflow-y-auto rounded border bg-muted/40 p-2 text-xs">
			{notesBlocks(notes).map((b, i) =>
				b.kind === "heading" ? (
					// biome-ignore lint/suspicious/noArrayIndexKey: the notes' blocks, in order (fixed for one release)
					<h3 key={i} className="text-sm font-semibold text-gold">
						<Spans spans={b.spans} />
					</h3>
				) : b.kind === "list" ? (
					// biome-ignore lint/suspicious/noArrayIndexKey: the notes' blocks, in order (fixed for one release)
					<ul key={i} className="list-disc pl-4">
						{b.items.map((item, j) => (
							// biome-ignore lint/suspicious/noArrayIndexKey: a list's points, in order
							<li key={j}>
								<Spans spans={item} />
							</li>
						))}
					</ul>
				) : (
					// biome-ignore lint/suspicious/noArrayIndexKey: the notes' blocks, in order (fixed for one release)
					<p key={i}>
						{b.lines.map((line, j) => (
							// biome-ignore lint/suspicious/noArrayIndexKey: a paragraph's lines, in order
							<span key={j}>
								{j > 0 && <br />}
								<Spans spans={line} />
							</span>
						))}
					</p>
				),
			)}
		</div>
	);
}

/** A line of the notes: plain, bold, code, and links (opened in a new tab). */
function Spans({ spans }: { spans: NotesSpan[] }) {
	return (
		<>
			{spans.map((s, i) =>
				s.href ? (
					// biome-ignore lint/suspicious/noArrayIndexKey: a line's parts, in order
					<a key={i} className="text-gold hover:underline" href={s.href} target="_blank" rel="noreferrer">
						{s.text}
					</a>
				) : s.bold ? (
					// biome-ignore lint/suspicious/noArrayIndexKey: a line's parts, in order
					<strong key={i}>{s.text}</strong>
				) : s.code ? (
					// biome-ignore lint/suspicious/noArrayIndexKey: a line's parts, in order
					<code key={i} className="rounded bg-muted px-1">
						{s.text}
					</code>
				) : (
					// biome-ignore lint/suspicious/noArrayIndexKey: a line's parts, in order
					<span key={i}>{s.text}</span>
				),
			)}
		</>
	);
}

/** Whole seconds left until a moment the app gave (s since 1970; 0: none), counting down each second: to the same
 * moment however often the box is opened (it started again from 60 each time: user). */
function useCountdown(until: number): number {
	const leftNow = () => Math.max(0, Math.ceil(until - Date.now() / 1000));
	const [left, setLeft] = useState(leftNow);
	useEffect(() => {
		const tick = () => setLeft(Math.max(0, Math.ceil(until - Date.now() / 1000)));
		tick();
		if (until <= Date.now() / 1000) return;
		const t = setInterval(tick, 1000);
		return () => clearInterval(t);
	}, [until]);
	return left;
}
