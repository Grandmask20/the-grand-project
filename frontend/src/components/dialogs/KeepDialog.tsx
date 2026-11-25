import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { duration } from "@/logic/Recheck";
import { useAppStore } from "@/store/AppStore";

/** Asks before keeping copies of the open atlas's screenshots (long work asks first: user), and says what it does:
 * a 1080p copy of each in the atlas folder's terrain/, the ones in its own folder then moved to used/, safe to delete
 * (user's design: the atlas keeps what was detected, and its pictures come from the copies). Screenshots added from now
 * on get theirs as they are added. */
export function KeepDialog() {
	const app = useAppClient();
	const queryClient = useQueryClient();
	const open = useAppStore((s) => s.keepCopies);
	const close = useAppStore((s) => s.askKeep);
	const showError = useAppStore((s) => s.showError);
	const info = useQuery({
		queryKey: ["keep-info"],
		queryFn: () => app.keepInfo(),
		enabled: open,
		staleTime: 0,
		gcTime: 0,
	});
	if (!open) return null;
	const d = info.data;
	const nothing = !!d && d.todo === 0 && d.move === 0;

	const start = () => {
		close(false);
		app
			.keep()
			.then(() => queryClient.invalidateQueries({ queryKey: AppQueryKeys.state }))
			.catch(showError);
	};

	return (
		<Dialog open onOpenChange={(o) => !o && close(false)}>
			<DialogContent className="max-h-[calc(100vh-2rem)] overflow-y-auto sm:max-w-lg">
				<DialogHeader>
					<DialogTitle>Keep copies of the screenshots?</DialogTitle>
					<DialogDescription className="text-foreground">
						A 1080p copy of each screenshot goes into this atlas's <code>terrain</code> folder: the map's pictures are
						read from it once a screenshot is gone. The screenshots in this atlas's own folder then move to its{" "}
						<code>used</code> folder, where they are safe to delete: the atlas keeps what was detected in them.
						Screenshots elsewhere (like Steam's folder) stay where they are. New screenshots get their copy as they are
						added.
					</DialogDescription>
				</DialogHeader>
				{info.isPending && <p className="text-muted-foreground text-sm">Reading the atlas…</p>}
				{info.isError && <p className="text-destructive text-sm">Couldn't read it: {String(info.error)}</p>}
				{d && (
					<ul className="ml-4 list-disc text-sm">
						<li>
							{d.shots} screenshots: {d.copied} copied already
							{d.todo > 0 && `, ${d.todo} to copy (about ${d.mb} MB, ${duration(d.seconds)})`}
						</li>
						{d.move > 0 && <li>{d.move} move to the used folder</li>}
						{d.lost > 0 && (
							<li className="text-amber-500">
								{d.lost} are gone and had no copy: their ground is lost where no other screenshot shows it
							</li>
						)}
						{nothing && <li>Everything is kept already.</li>}
					</ul>
				)}
				<DialogFooter>
					<Button variant="outline" onClick={() => close(false)}>
						{nothing ? "Close" : "Not now"}
					</Button>
					{!nothing && (
						<Button autoFocus disabled={!d} onClick={start}>
							Keep copies
						</Button>
					)}
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
