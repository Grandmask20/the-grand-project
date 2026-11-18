import { ArrowUpIcon, FileImageIcon, FileJsonIcon, FolderIcon, HomeIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useFolder } from "@/hooks/atlas/UseFolder";
import { useAppStore } from "@/store/AppStore";
import { cn } from "@/utils/Cn";
import { size } from "@/utils/Format";

/** Picks files or a folder on this computer (the app lists them: a page can't see full paths itself). */
export function FileBrowserDialog() {
	const pick = useAppStore((s) => s.filePick);
	const close = useAppStore((s) => s.pickFiles);
	const [path, setPath] = useState<string | null>(null);
	const [typed, setTyped] = useState("");
	const [chosen, setChosen] = useState<string[]>([]);
	const [name, setName] = useState("");
	const listing = useFolder(pick ? path : null, !pick?.folders || !!pick?.save);

	useEffect(() => {
		if (!pick) return;
		setPath(pick.start ?? "");
		setChosen([]);
		setName(pick.save ?? "");
	}, [pick]);

	useEffect(() => {
		if (listing.data) setTyped(listing.data.path);
	}, [listing.data]);

	if (!pick) return null;
	const here = listing.data?.path ?? "";
	const sep = here.includes("\\") ? "\\" : "/";
	const join = (dir: string, n: string) => (dir.endsWith(sep) ? `${dir}${n}` : `${dir}${sep}${n}`);

	const done = (paths: string[]) => {
		close(null);
		if (paths.length) pick.onPick(paths);
	};

	const ok = () => {
		if (pick.save) return done([join(here, name.trim() || pick.save)]);
		if (pick.folders) return done([chosen[0] ?? here]);
		done(chosen);
	};

	const visible = (listing.data?.entries ?? []).filter((e) => e.dir || !pick.folders || pick.save);
	return (
		<Dialog open onOpenChange={(open) => !open && close(null)}>
			<DialogContent className="sm:max-w-2xl">
				<DialogHeader>
					<DialogTitle>{pick.title}</DialogTitle>
				</DialogHeader>
				<div className="flex gap-1.5">
					<Button size="icon-sm" variant="outline" aria-label="Home folder" onClick={() => setPath("")}>
						<HomeIcon />
					</Button>
					<Button
						size="icon-sm"
						variant="outline"
						aria-label="Up one folder"
						disabled={!listing.data?.parent}
						onClick={() => setPath(listing.data?.parent ?? "")}
					>
						<ArrowUpIcon />
					</Button>
					<Input
						aria-label="Folder"
						value={typed}
						onChange={(e) => setTyped(e.target.value)}
						onKeyDown={(e) => e.key === "Enter" && setPath(typed)}
						className="font-mono text-xs"
					/>
				</div>
				{listing.isError && <p className="text-destructive">{listing.error.message}</p>}
				<ul className="h-80 overflow-y-auto rounded border text-sm" aria-label="Files">
					{visible.map((e) => {
						const on = chosen.includes(e.path);
						return (
							<li key={e.path}>
								<button
									type="button"
									className={cn("flex w-full items-center gap-2 px-2 py-1 text-left hover:bg-accent", on && "bg-accent text-gold")}
									onClick={() => {
										if (e.dir && !pick.folders) return setPath(e.path);
										if (pick.save) return e.dir ? setPath(e.path) : setName(e.name);
										if (pick.multiple) setChosen(on ? chosen.filter((p) => p !== e.path) : [...chosen, e.path]);
										else setChosen([e.path]);
									}}
									onDoubleClick={() => {
										if (e.dir) setPath(e.path);
										else if (!pick.folders && !pick.save) done([e.path]);
									}}
								>
									{e.dir ? (
										<FolderIcon className="size-4 text-gold" />
									) : e.name.endsWith(".json") ? (
										<FileJsonIcon className="size-4" />
									) : (
										<FileImageIcon className="size-4" />
									)}
									<span className="flex-1 truncate">{e.name}</span>
									{!e.dir && <span className="text-xs text-muted-foreground">{size(e.size)}</span>}
								</button>
							</li>
						);
					})}
					{listing.data?.truncated && <li className="px-2 py-1 text-muted-foreground">(more not listed)</li>}
				</ul>
				{pick.save && (
					<Input aria-label="File name" value={name} onChange={(e) => setName(e.target.value)} placeholder={pick.save} />
				)}
				<DialogFooter className="items-center">
					<span className="mr-auto text-xs text-muted-foreground">
						{pick.folders && !pick.save
							? "Pick a folder (or open one and press Choose)."
							: pick.multiple
								? `${chosen.length} picked (click to pick several; select all with the button)`
								: "Double-click a folder to open it."}
					</span>
					{pick.multiple && (
						<Button
							variant="outline"
							onClick={() => setChosen(visible.filter((e) => !e.dir).map((e) => e.path))}
						>
							Select all
						</Button>
					)}
					<Button variant="outline" onClick={() => close(null)}>
						Cancel
					</Button>
					<Button onClick={ok} disabled={!pick.folders && !pick.save && !chosen.length}>
						{pick.save ? "Create" : pick.folders ? "Choose" : "Open"}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
