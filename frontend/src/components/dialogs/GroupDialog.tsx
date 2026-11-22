import { useEffect, useState } from "react";
import { sameAtlas } from "@/api/Http";
import { LookPicker } from "@/components/bookmarks/LookPicker";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useMeta } from "@/hooks/app/UseMeta";
import { useAppStore } from "@/store/AppStore";

/**
 * A bookmark group's pen (user: it opens a menu for the group's icon and colour): its name, and its look, which its
 * bookmarks without one of their own take.
 */
export function GroupDialog() {
	const app = useAppClient();
	const edit = useAppStore((s) => s.groupEdit);
	const close = useAppStore((s) => s.editGroup);
	const showError = useAppStore((s) => s.showError);
	const meta = useMeta().data;
	const [name, setName] = useState("");
	const [colour, setColour] = useState("");
	const [icon, setIcon] = useState("");
	const [plain, setPlain] = useState(false);
	const [error, setError] = useState("");

	useEffect(() => {
		setName(edit?.name ?? "");
		setColour(edit?.colour ?? "");
		setIcon(edit?.icon ?? "");
		setPlain(edit?.plain ?? false);
		setError("");
	}, [edit]);

	if (!edit) return null;

	const save = async () => {
		const to = name.trim();
		if (!to) return setError("A group needs a name.");
		const mine = edit;
		// both steps for the atlas this was opened on: after a switch, nothing more is sent (the rename's answer is
		// refused then too: Http)
		const same = sameAtlas();
		try {
			if (to !== edit.name) {
				await app.renameGroup(edit.name, to);
				edit.onRenamed?.(to);
			}
			if (same() && (colour !== edit.colour || icon !== edit.icon || plain !== edit.plain))
				await app.styleGroup(to, colour, icon, plain);
			// closed only if this is still the group being edited (cancelled and another opened meanwhile: kept)
			if (useAppStore.getState().groupEdit === mine) close(null);
		} catch (e) {
			showError(e);
		}
	};

	return (
		<Dialog open onOpenChange={(open) => !open && close(null)}>
			<DialogContent className="sm:max-w-md">
				<DialogHeader>
					<DialogTitle>Edit group</DialogTitle>
				</DialogHeader>
				<form
					className="flex flex-col gap-3"
					onSubmit={(e) => {
						e.preventDefault();
						void save();
					}}
				>
					<div className="flex flex-col gap-1.5">
						<Label htmlFor="group-name">Name</Label>
						<Input id="group-name" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
					</div>
					<LookPicker
						colour={colour}
						icon={icon}
						plain={plain}
						onColour={setColour}
						onIcon={setIcon}
						onPlain={setPlain}
						fallback={{ colour: meta?.colours.bookmark ?? "#c8a45c", from: "standard" }}
					/>
					<p className="text-xs text-muted-foreground">Its bookmarks without a look of their own take this one.</p>
					{error && <p className="text-destructive">{error}</p>}
					<DialogFooter>
						<Button type="button" variant="outline" onClick={() => close(null)}>
							Cancel
						</Button>
						<Button type="submit">Save</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
