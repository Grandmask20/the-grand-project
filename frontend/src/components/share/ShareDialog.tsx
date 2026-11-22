import { CopyIcon, EyeIcon, XIcon } from "lucide-react";
import { type ReactNode, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { type Link, useShareStore } from "@/store/ShareStore";

/** A code to send, with Copy (said "Copied" a moment). */
function CodeBox({ code, label }: { code: string; label: string }) {
	const [copied, setCopied] = useState(false);
	return (
		<div className="flex flex-col gap-1">
			<Label className="text-xs text-muted-foreground">{label}</Label>
			<div className="flex gap-1.5">
				<Textarea
					readOnly
					value={code}
					aria-label={label}
					className="h-16 resize-none font-mono text-xs break-all"
					onFocus={(e) => e.currentTarget.select()}
				/>
				<Button
					size="sm"
					variant="outline"
					onClick={() => {
						void navigator.clipboard?.writeText(code).then(() => {
							setCopied(true);
							setTimeout(() => setCopied(false), 1500);
						});
					}}
				>
					<CopyIcon />
					{copied ? "Copied" : "Copy"}
				</Button>
			</div>
		</div>
	);
}

/** A code to paste, with its button. */
function PasteBox({
	label,
	action,
	onGo,
	error,
}: {
	label: string;
	action: string;
	onGo: (code: string) => void;
	error?: string;
}) {
	const [code, setCode] = useState("");
	return (
		<div className="flex flex-col gap-1">
			<div className="flex gap-1.5">
				<Textarea
					value={code}
					onChange={(e) => setCode(e.target.value)}
					placeholder={label}
					aria-label={label}
					className="h-16 resize-none font-mono text-xs"
				/>
				<Button size="sm" disabled={!code.trim()} onClick={() => onGo(code)}>
					{action}
				</Button>
			</div>
			{error && <p className="text-xs text-destructive">{error}</p>}
		</div>
	);
}

const Live = ({ who }: { who: string }) => (
	<span className="flex items-center gap-1.5 text-xs text-success-foreground">
		<span className="size-2 rounded-full bg-success-foreground" aria-hidden />
		live{who ? ` with ${who}` : ""}
	</span>
);

/** A link's row: where it is in its two codes, then live, or closed. */
function LinkRow({ link }: { link: Link }) {
	const s = useShareStore();
	const end = (
		<Button size="xs" variant="ghost" aria-label="End this link" title="End this link" onClick={() => s.stop(link.id)}>
			<XIcon />
		</Button>
	);
	const head = (body: ReactNode) => (
		<div className="flex items-center gap-2 text-sm">
			<span className="min-w-0 flex-1">{body}</span>
			{end}
		</div>
	);
	return (
		<div className="flex flex-col gap-2 rounded border p-2">
			{link.state === "making" && head(<span className="text-muted-foreground">Making the code… (a few seconds)</span>)}
			{link.state === "invited" && (
				<>
					{head(<span>Invite: send it to your friend, then paste their reply</span>)}
					<CodeBox code={link.code} label="Your invite" />
					<PasteBox label="Their reply" action="Connect" error={link.error} onGo={(c) => void s.connect(link.id, c)} />
				</>
			)}
			{link.state === "replied" && (
				<>
					{head(<span>Send this reply back to your friend; the link opens when they paste it</span>)}
					<CodeBox code={link.code} label="Your reply" />
				</>
			)}
			{link.state === "connecting" && head(<span className="text-muted-foreground">Connecting…</span>)}
			{link.state === "live" &&
				head(
					<span className="flex flex-wrap items-center gap-2">
						<Live who={link.friend} />
						{link.role === "watch" && link.atlas && (
							<>
								<span className="truncate text-muted-foreground">{link.atlas.name}</span>
								<Button
									size="xs"
									variant="outline"
									onClick={() => {
										s.view(link.id);
										s.setOpen(false);
									}}
								>
									<EyeIcon />
									Open
								</Button>
							</>
						)}
						{link.role === "share" && <span className="text-xs text-muted-foreground">sees your atlas</span>}
					</span>,
				)}
			{link.state === "closed" &&
				head(
					<span className="text-muted-foreground">
						Link closed{link.friend ? ` (${link.friend})` : ""}. {link.error || "Make new codes to link again."}
					</span>,
				)}
		</div>
	);
}

/**
 * Live sharing (canvas: Share my atlas): your atlas to a friend, a friend's atlas to you, browser to browser. Two
 * codes pasted by hand link you (no server of our own: user); after that, your atlas and position go as they change.
 */
export function ShareDialog() {
	const s = useShareStore();
	const [joinError, setJoinError] = useState("");
	const shares = s.links.filter((l) => l.role === "share");
	const watches = s.links.filter((l) => l.role === "watch");
	return (
		<Dialog open={s.open} onOpenChange={s.setOpen}>
			<DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
				<DialogHeader>
					<DialogTitle>Live sharing</DialogTitle>
					<DialogDescription>
						Your browser links straight to your friend's: nothing goes through a server, and their atlas never changes
						yours. Keep this page open while you share.
					</DialogDescription>
				</DialogHeader>
				<div className="flex items-center gap-2">
					<Label htmlFor="share-name" className="shrink-0">
						Your name
					</Label>
					<Input
						id="share-name"
						value={s.name}
						maxLength={40}
						placeholder="What friends see"
						onChange={(e) => s.setName(e.target.value)}
					/>
				</div>
				<div className="grid gap-4 md:grid-cols-2">
					<section aria-label="Share my atlas" className="flex flex-col gap-2">
						<h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Share my atlas</h3>
						{shares.map((l) => (
							<LinkRow key={l.id} link={l} />
						))}
						<Button size="sm" variant="outline" className="self-start" onClick={() => void s.share()}>
							New invite
						</Button>
						<p className="text-xs text-muted-foreground">
							One invite per friend. They see your maps, paths, landmarks and where you are, live.
						</p>
					</section>
					<section aria-label="Watch a friend" className="flex flex-col gap-2">
						<h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Watch a friend</h3>
						{watches.map((l) => (
							<LinkRow key={l.id} link={l} />
						))}
						<PasteBox
							label="Their invite"
							action="Join"
							error={joinError}
							onGo={(c) =>
								void s.join(c).then(
									() => setJoinError(""),
									(e: Error) => setJoinError(e.message),
								)
							}
						/>
					</section>
				</div>
				<p className="text-xs text-muted-foreground">
					If a link never opens, one of your connections doesn't allow direct links (some mobile and shared
					connections); on the same network it always works.
				</p>
			</DialogContent>
		</Dialog>
	);
}
