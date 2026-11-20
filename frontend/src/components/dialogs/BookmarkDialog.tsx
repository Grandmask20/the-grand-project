import { useEffect, useState } from "react";
import { ComboInput } from "@/components/common/ComboInput";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useMeta } from "@/hooks/app/UseMeta";
import { useBookmarks } from "@/hooks/bookmarks/UseBookmarks";
import { useAppStore } from "@/store/AppStore";

/** Adds or edits a bookmark: name, group, note. */
export function BookmarkDialog() {
	const app = useAppClient();
	const edit = useAppStore((s) => s.bookmarkEdit);
	const close = useAppStore((s) => s.editBookmark);
	const showError = useAppStore((s) => s.showError);
	const meta = useMeta().data;
	const groups = useBookmarks(!!edit).data?.groups.map((g) => g.name) ?? [];
	const [name, setName] = useState("");
	const [group, setGroup] = useState("Other");
	const [note, setNote] = useState("");
	const [error, setError] = useState("");

	useEffect(() => {
		setName(edit?.name ?? "");
		setGroup(edit?.group ?? "Other");
		setNote(edit?.note ?? "");
		setError("");
	}, [edit]);

	if (!edit) return null;
	const options = [...new Set([...groups, ...(meta?.categories ?? [])])];

	const save = async () => {
		if (!name.trim()) return setError("A bookmark needs a name.");
		try {
			const mine = edit;
			if (edit.id === null) await app.addBookmark({ x: edit.x, y: edit.y, name, group, note, route: edit.route });
			else await app.editBookmark(edit.id, { name, group, note });
			// closed only if this is still the bookmark being edited (cancelled and another opened meanwhile: kept)
			if (useAppStore.getState().bookmarkEdit === mine) close(null);
		} catch (e) {
			if (e instanceof Error && /already a bookmark/.test(e.message)) setError(e.message);
			else showError(e);
		}
	};

	return (
		<Dialog open onOpenChange={(open) => !open && close(null)}>
			<DialogContent className="sm:max-w-md">
				<DialogHeader>
					<DialogTitle>{edit.route ? "Save route" : edit.id === null ? "Add bookmark" : "Edit bookmark"}</DialogTitle>
				</DialogHeader>
				<form
					className="flex flex-col gap-3"
					onSubmit={(e) => {
						e.preventDefault();
						void save();
					}}
				>
					<div className="flex flex-col gap-1.5">
						<Label htmlFor="bm-name">Name</Label>
						<Input id="bm-name" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
					</div>
					<div className="flex flex-col gap-1.5">
						<Label htmlFor="bm-group">Group</Label>
						<ComboInput id="bm-group" value={group} onChange={setGroup} options={options} />
					</div>
					<div className="flex flex-col gap-1.5">
						<Label htmlFor="bm-note">Note</Label>
						<Textarea id="bm-note" value={note} onChange={(e) => setNote(e.target.value)} />
					</div>
					<p className="text-xs text-muted-foreground">
						at {edit.x.toFixed(0)}, {edit.y.toFixed(0)}
					</p>
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
