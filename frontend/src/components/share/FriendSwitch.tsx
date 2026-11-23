import { UndoIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAppState } from "@/hooks/app/UseAppState";
import { useAtlasActions } from "@/hooks/atlas/UseAtlasActions";
import { useFriends } from "@/hooks/share/UseFriends";

/** While a friend's atlas is open: whose, that it is read-only, and the way back to yours. */
export function FriendSwitch() {
	const friend = useAppState().data?.atlas?.friend;
	const own = useFriends().data?.own ?? null;
	const actions = useAtlasActions();
	if (!friend) return null;
	return (
		<span className="flex items-center gap-2 rounded border border-gold/60 px-2 py-0.5 text-xs">
			<span>
				<span className="font-semibold text-gold">{friend}'s atlas</span>
				<span className="text-muted-foreground"> · read-only</span>
			</span>
			{own && (
				<Button size="xs" variant="ghost" onClick={() => void actions.openAtlas(own)}>
					<UndoIcon />
					Back to my atlas
				</Button>
			)}
		</span>
	);
}
