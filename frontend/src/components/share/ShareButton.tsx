import { UsersIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useShareStore } from "@/store/ShareStore";

/** The top bar's Share: opens live sharing; a dot and a count while links are live. */
export function ShareButton() {
	const setOpen = useShareStore((s) => s.setOpen);
	const live = useShareStore((s) => s.links.filter((l) => l.state === "live").length);
	return (
		<Button
			size="sm"
			variant="ghost"
			onClick={() => setOpen(true)}
			title="Live sharing: your atlas to friends, theirs to you"
			aria-label={live ? `Share (${live} live)` : "Share"}
		>
			<UsersIcon />
			Share
			{live > 0 && (
				<span className="flex items-center gap-1 text-xs text-success-foreground">
					<span className="size-2 rounded-full bg-success-foreground" aria-hidden />
					{live}
				</span>
			)}
		</Button>
	);
}
