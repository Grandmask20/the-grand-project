import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useAppStore } from "@/store/AppStore";

/** Asks yes / no before something is done. */
export function ConfirmDialog() {
	const c = useAppStore((s) => s.confirm);
	const close = useAppStore((s) => s.askConfirm);
	if (!c) return null;
	return (
		<Dialog open onOpenChange={(open) => !open && close(null)}>
			<DialogContent className="sm:max-w-md">
				<DialogHeader>
					<DialogTitle>{c.title}</DialogTitle>
					<DialogDescription className="whitespace-pre-wrap text-foreground">{c.text}</DialogDescription>
				</DialogHeader>
				<DialogFooter>
					<Button variant="outline" onClick={() => close(null)}>
						Cancel
					</Button>
					<Button
						variant={c.danger ? "destructive" : "default"}
						autoFocus
						onClick={() => {
							close(null);
							c.onYes();
						}}
					>
						{c.yes}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
