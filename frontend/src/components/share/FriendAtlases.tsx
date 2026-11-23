import { UsersIcon } from "lucide-react";
import { useAppState } from "@/hooks/app/UseAppState";
import { useAtlasActions } from "@/hooks/atlas/UseAtlasActions";
import { useFriends } from "@/hooks/share/UseFriends";
import { cn } from "@/utils/Cn";

/** How long ago, in words ("just now", "5 min ago", "3 h ago", "2 days ago"). */
export function ago(seconds: number | null, now = Date.now() / 1000): string {
	if (seconds === null) return "";
	const d = Math.max(0, now - seconds);
	if (d < 60) return "just now";
	if (d < 3600) return `${Math.floor(d / 60)} min ago`;
	if (d < 86400) return `${Math.floor(d / 3600)} h ago`;
	return `${Math.floor(d / 86400)} days ago`;
}

/**
 * The Atlases tab's friends' atlases (live sharing): each one kept here, as it last came; click one to open it,
 * read-only and as they see it, and your own atlas to go back to (user: "one item to switch between friend atlas
 * and their own").
 */
export function FriendAtlases() {
	const friends = useFriends().data;
	const state = useAppState().data;
	const actions = useAtlasActions();
	if (!friends?.friends.length) return null;
	const viewing = !!state?.atlas?.friend;
	return (
		<section aria-label="Friends' atlases" className="flex flex-col gap-1.5">
			<h3 className="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
				<UsersIcon className="size-3.5" />
				Friends' atlases
			</h3>
			{viewing && friends.own && (
				<button
					type="button"
					className="rounded-md border border-gold/60 p-2 text-left hover:bg-accent"
					onClick={() => void actions.openAtlas(friends.own as string)}
				>
					<span className="font-semibold">Back to my atlas</span>
				</button>
			)}
			{friends.friends.map((f) => (
				<button
					key={f.json}
					type="button"
					title={f.json}
					disabled={state?.busy || f.open}
					className={cn(
						"flex flex-col rounded-md border p-2 text-left hover:bg-accent",
						f.open && "border-gold bg-accent/60",
					)}
					onClick={() => void actions.openAtlas(f.json)}
				>
					<span className="font-semibold">{f.name}'s atlas</span>
					<span className="text-xs text-muted-foreground">
						{f.maps !== null ? `${f.maps} maps · ` : ""}
						{f.updated ? `came ${ago(f.updated)}` : ""} · read-only
					</span>
					{f.open && <span className="text-xs text-gold">open</span>}
				</button>
			))}
		</section>
	);
}
