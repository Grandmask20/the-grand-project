import {
	ArrowUpIcon,
	ChevronRightIcon,
	FileImageIcon,
	FileJsonIcon,
	FolderIcon,
	FolderOpenIcon,
	HomeIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import type { FsEntry } from "@/domain/atlas/FsListing";
import { useFolder } from "@/hooks/atlas/UseFolder";
import { useAppStore } from "@/store/AppStore";
import { cn } from "@/utils/Cn";
import { size } from "@/utils/Format";
import { ancestors } from "@/utils/Paths";

const when = (t?: number) =>
	t ? new Date(t * 1000).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" }) : "";

/**
 * Picks files or a folder on this computer (the app lists them: a page can't see full paths itself). Laid out like
 * Steam's folder picker (user): the path as clickable folders, a folder tree (the folders above this one, and the
 * ones next to it), and one list with the same columns and clicks whatever is picked: a click selects, a double-click
 * opens a folder or picks a file.
 */
export function FileBrowserDialog() {
	const pick = useAppStore((s) => s.filePick);
	const close = useAppStore((s) => s.pickFiles);
	const [path, setPath] = useState<string | null>(null);
	const [typed, setTyped] = useState("");
	// typed in the folder box since a folder was last asked for: a listing coming in then leaves the box as typed (the
	// start folder's listing, late, wrote over a path being typed, and Enter opened the start folder again: CI)
	const edited = useRef(false);
	const [chosen, setChosen] = useState<string[]>([]);
	const [name, setName] = useState("");
	const listing = useFolder(pick ? path : null, !pick?.folders || !!pick?.save);
	const parentPath = listing.data?.parent ?? null;
	const siblings = useFolder(pick && parentPath ? parentPath : null, false);

	useEffect(() => {
		if (!pick) return;
		setPath(pick.start ?? "");
		edited.current = false;
		setChosen([]);
		setName(pick.save ?? "");
	}, [pick]);

	useEffect(() => {
		if (listing.data && !edited.current) setTyped(listing.data.path);
	}, [listing.data]);

	if (!pick) return null;
	const here = listing.data?.path ?? "";
	const sep = here.includes("\\") ? "\\" : "/";
	const join = (dir: string, n: string) => (dir.endsWith(sep) ? `${dir}${n}` : `${dir}${sep}${n}`);
	const go = (p: string) => {
		edited.current = false;
		setPath(p);
		setChosen([]); // a folder picked in another folder is not what Choose should return (CodeRabbit)
	};

	const done = (paths: string[]) => {
		close(null);
		if (paths.length) pick.onPick(paths);
	};

	const ok = () => {
		if (pick.save) return done([join(here, name.trim() || pick.save)]);
		if (pick.folders) return done([chosen[0] ?? here]);
		done(chosen);
	};

	const click = (e: FsEntry) => {
		if (pick.save) return e.dir ? setChosen([e.path]) : setName(e.name);
		if (e.dir && !pick.folders) return setChosen([]); // only files are picked here: a folder is opened
		const on = chosen.includes(e.path);
		if (pick.multiple && !e.dir) setChosen(on ? chosen.filter((p) => p !== e.path) : [...chosen, e.path]);
		else setChosen([e.path]);
	};

	const visible = (listing.data?.entries ?? []).filter((e) => e.dir || !pick.folders || pick.save);
	const chain = ancestors(here);
	const nextTo = (siblings.data?.entries ?? []).filter((e) => e.dir);
	const depth = Math.max(0, chain.length - 1);

	return (
		<Dialog open onOpenChange={(open) => !open && close(null)}>
			<DialogContent className="sm:max-w-4xl">
				<DialogHeader>
					<DialogTitle>{pick.title}</DialogTitle>
				</DialogHeader>
				<div className="flex gap-1.5">
					<Button size="icon-sm" variant="outline" aria-label="Home folder" onClick={() => go("")}>
						<HomeIcon />
					</Button>
					<Button
						size="icon-sm"
						variant="outline"
						aria-label="Up one folder"
						disabled={!parentPath}
						onClick={() => go(parentPath ?? "")}
					>
						<ArrowUpIcon />
					</Button>
					<Input
						aria-label="Folder"
						value={typed}
						onChange={(e) => {
							edited.current = true;
							setTyped(e.target.value);
						}}
						onKeyDown={(e) => e.key === "Enter" && go(typed)}
						className="font-mono text-xs"
					/>
				</div>
				{/* the path as clickable folders, like the Windows and Steam pickers */}
				<nav className="flex flex-wrap items-center gap-0.5 text-xs" aria-label="Path">
					<button type="button" className="rounded px-1 py-0.5 hover:bg-accent" onClick={() => go("drives")}>
						This PC
					</button>
					{chain.map((a) => (
						<span key={a.path} className="flex items-center gap-0.5">
							<ChevronRightIcon className="size-3 text-muted-foreground" />
							<button
								type="button"
								className={cn("rounded px-1 py-0.5 hover:bg-accent", a.path === here && "text-gold")}
								onClick={() => go(a.path)}
							>
								{a.name}
							</button>
						</span>
					))}
				</nav>
				{listing.isError && <p className="text-destructive">{listing.error.message}</p>}
				<div className="flex h-80 gap-2">
					{/* the folder tree: the folders above, then this folder among the ones next to it */}
					<ul className="w-56 shrink-0 overflow-y-auto rounded border py-1 text-xs" aria-label="Folders">
						{chain.slice(0, -1).map((a, i) => (
							<li key={a.path}>
								<button
									type="button"
									className="flex w-full items-center gap-1 truncate py-0.5 pr-1 text-left hover:bg-accent"
									style={{ paddingLeft: 6 + i * 10 }}
									onClick={() => go(a.path)}
								>
									<FolderOpenIcon className="size-3.5 shrink-0 text-gold" />
									<span className="truncate">{a.name}</span>
								</button>
							</li>
						))}
						{(nextTo.length ? nextTo : chain.slice(-1).map((a) => ({ name: a.name, path: a.path }))).map((e) => (
							<li key={e.path}>
								<button
									type="button"
									className={cn(
										"flex w-full items-center gap-1 truncate py-0.5 pr-1 text-left hover:bg-accent",
										e.path === here && "bg-accent text-gold",
									)}
									style={{ paddingLeft: 6 + depth * 10 }}
									ref={e.path === here ? (el) => el?.scrollIntoView({ block: "nearest" }) : undefined}
									onClick={() => go(e.path)}
								>
									{e.path === here ? (
										<FolderOpenIcon className="size-3.5 shrink-0 text-gold" />
									) : (
										<FolderIcon className="size-3.5 shrink-0 text-gold" />
									)}
									<span className="truncate">{e.name}</span>
								</button>
								{/* the open folder unfolds in the tree, as in Steam's picker (user: the tree didn't open) */}
								{e.path === here && (
									<ul>
										{(listing.data?.entries ?? [])
											.filter((c) => c.dir)
											.map((c) => (
												<li key={c.path}>
													<button
														type="button"
														className="flex w-full items-center gap-1 truncate py-0.5 pr-1 text-left hover:bg-accent"
														style={{ paddingLeft: 6 + (depth + 1) * 10 }}
														onClick={() => go(c.path)}
													>
														<FolderIcon className="size-3.5 shrink-0 text-gold" />
														<span className="truncate">{c.name}</span>
													</button>
												</li>
											))}
									</ul>
								)}
							</li>
						))}
					</ul>
					<div className="flex min-w-0 flex-1 flex-col rounded border text-sm">
						<div className="grid grid-cols-[1fr_9rem_5rem] gap-2 border-b px-2 py-1 text-xs text-muted-foreground">
							<span>Name</span>
							<span>Modified</span>
							<span className="text-right">Size</span>
						</div>
						<ul className="min-h-0 flex-1 overflow-y-auto" aria-label="Files">
							{visible.map((e) => {
								const on = chosen.includes(e.path);
								return (
									<li key={e.path}>
										<button
											type="button"
											className={cn(
												"grid w-full grid-cols-[1fr_9rem_5rem] items-center gap-2 px-2 py-1 text-left hover:bg-accent",
												on && "bg-accent text-gold",
											)}
											onClick={() => click(e)}
											onDoubleClick={() => {
												if (e.dir) go(e.path);
												else if (!pick.folders && !pick.save) done([e.path]);
											}}
										>
											<span className="flex min-w-0 items-center gap-2">
												{e.dir ? (
													<FolderIcon className="size-4 shrink-0 text-gold" />
												) : e.name.endsWith(".json") ? (
													<FileJsonIcon className="size-4 shrink-0" />
												) : (
													<FileImageIcon className="size-4 shrink-0" />
												)}
												<span className="truncate">{e.name}</span>
											</span>
											<span className="truncate text-xs text-muted-foreground">{when(e.mtime)}</span>
											<span className="text-right text-xs text-muted-foreground">{e.dir ? "" : size(e.size)}</span>
										</button>
									</li>
								);
							})}
							{!visible.length && listing.data && <li className="px-2 py-1 text-muted-foreground">(empty)</li>}
							{listing.data?.truncated && <li className="px-2 py-1 text-muted-foreground">(more not listed)</li>}
						</ul>
					</div>
				</div>
				{pick.save && (
					<Input
						aria-label="File name"
						value={name}
						onChange={(e) => setName(e.target.value)}
						placeholder={pick.save}
					/>
				)}
				<DialogFooter className="items-center">
					<span className="mr-auto text-xs text-muted-foreground">
						{pick.folders && !pick.save
							? `Pick a folder (or open one): ${chosen[0] ?? here}`
							: pick.multiple
								? `${chosen.length} picked (click to pick several)`
								: "Click to pick, double-click to open."}
					</span>
					{pick.multiple && (
						<Button variant="outline" onClick={() => setChosen(visible.filter((e) => !e.dir).map((e) => e.path))}>
							Select all
						</Button>
					)}
					<Button variant="outline" onClick={() => close(null)}>
						Cancel
					</Button>
					<Button onClick={ok} disabled={!here || (!pick.folders && !pick.save && !chosen.length)}>
						{pick.save ? "Create" : pick.folders ? "Choose" : "Open"}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
