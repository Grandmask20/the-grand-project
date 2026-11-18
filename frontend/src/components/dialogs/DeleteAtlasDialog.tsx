import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAtlases } from "@/hooks/atlas/UseAtlases";
import { useAppStore } from "@/store/AppStore";

/** What to do with an atlas: stop tracking it (files stay) or delete it and its data (never the screenshots). */
export function DeleteAtlasDialog() {
	const app = useAppClient();
	const json = useAppStore((s) => s.deleteAtlas);
	const close = useAppStore((s) => s.askDeleteAtlas);
	const showError = useAppStore((s) => s.showError);
	const atlases = useAtlases();
	const [sure, setSure] = useState(false);
	if (!json) return null;
	const name = atlases.data?.find((a) => a.json === json)?.name ?? json;

	const done = () => {
		setSure(false);
		close(null);
	};

	return (
		<Dialog open onOpenChange={(open) => !open && done()}>
			<DialogContent className="sm:max-w-lg">
				<DialogHeader>
					<DialogTitle>What should happen to “{name}”?</DialogTitle>
					<DialogDescription className="break-all">
						{json}
						<br />
						<br />
						Your screenshots are never deleted.
					</DialogDescription>
				</DialogHeader>
				{sure && (
					<p className="text-destructive">
						Delete the atlas, its saved detections, map images and undo copies for good? This can't be undone.
					</p>
				)}
				<DialogFooter>
					<Button variant="outline" onClick={done}>
						Cancel
					</Button>
					<Button
						variant="outline"
						onClick={() => {
							done();
							void app.forgetAtlas(json).catch(showError);
						}}
					>
						Stop tracking atlas
					</Button>
					<Button
						variant="destructive"
						onClick={() => {
							if (!sure) return setSure(true);
							done();
							void app
								.deleteAtlas(json)
								.then((r) => r.failed.length && showError(`Some files could not be deleted:\n${r.failed.join("\n")}`))
								.catch(showError);
						}}
					>
						{sure ? "Yes, delete it" : "Delete whole atlas and its data"}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
