import { CopyIcon, EyeIcon, XIcon } from "lucide-react";
import { type ReactNode, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useAppState } from "@/hooks/app/UseAppState";
import { useAtlasActions } from "@/hooks/atlas/UseAtlasActions";
import { relayOn } from "@/logic/share/RelayConfig";
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
	const actions = useAtlasActions();
	const openPath = useAppState().data?.atlas?.path ?? "";
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
			{link.state === "invited" && link.via === "room" && (
				<>
					{head(<span>Invite: send it to your friends. Nobody is watching yet.</span>)}
					<CodeBox code={link.code} label="Your invite" />
				</>
			)}
			{link.state === "invited" && link.via === "direct" && (
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
			{link.state === "connecting" &&
				head(
					<span className="text-muted-foreground">
						{link.via === "room" ? "Waiting for them to be online…" : "Connecting…"}
					</span>,
				)}
			{link.state === "live" &&
				head(
					<span className="flex flex-wrap items-center gap-2">
						<Live who={link.friend} />
						{link.role === "watch" && link.atlasPath && (
							<>
								<span className="truncate text-muted-foreground">{link.atlasName}</span>
								{openPath === link.atlasPath ? (
									<span className="text-xs text-gold">open</span>
								) : (
									<Button
										size="xs"
										variant="outline"
										onClick={() => {
											void actions.openAtlas(link.atlasPath);
											s.setOpen(false);
										}}
									>
										<EyeIcon />
										Open
									</Button>
								)}
							</>
						)}
						{link.role === "watch" && link.file && !link.atlasPath && (
							<span className="text-xs text-muted-foreground">their atlas is coming…</span>
						)}
						{link.role === "share" && (
							<span className="text-xs text-muted-foreground">
								{link.via === "room" ? `${link.watchers} watching your atlas` : "sees your atlas"}
							</span>
						)}
					</span>,
				)}
			{link.state === "live" && link.role === "share" && link.via === "room" && (
				<CodeBox code={link.code} label="Your invite (more friends can join with it)" />
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
	const rooms = relayOn();
	const [joinError, setJoinError] = useState("");
	const shares = s.links.filter((l) => l.role === "share");
	const watches = s.links.filter((l) => l.role === "watch");
	return (
		<Dialog open={s.open} onOpenChange={s.setOpen}>
			<DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
				<DialogHeader>
					<DialogTitle>Live sharing</DialogTitle>
					<DialogDescription>
						{rooms
							? "Links go through the app's relay, sealed in your browser: the relay can't read your atlas. "
							: "Your browser links straight to your friend's: nothing goes through a server. "}
						Their atlas never changes yours. Keep this page open while you share.
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
						<Button
							size="sm"
							variant="outline"
							className="self-start"
							onClick={() => void (rooms ? s.shareRoom() : s.share())}
						>
							New invite
						</Button>
						<p className="text-xs text-muted-foreground">
							{rooms ? "One invite for all your friends. " : "One invite per friend. "}
							They see your maps, paths, landmarks and where you are, live.
						</p>
						{rooms && (
							<Button size="xs" variant="ghost" className="self-start" onClick={() => void s.share()}>
								Direct invite instead (no relay)
							</Button>
						)}
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
					{rooms
						? "Through the relay a link works on any network. A direct invite needs no third party, but can't open when one of your networks doesn't allow direct links (some mobile and shared ones)."
						: "If a link never opens, one of your connections doesn't allow direct links (some mobile and shared connections); on the same network it always works."}
				</p>
			</DialogContent>
		</Dialog>
	);
}
