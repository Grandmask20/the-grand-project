import { EllipsisIcon, FolderOpenIcon, PlusIcon } from "lucide-react";
import { useState } from "react";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuSeparator,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import { useAtlasActions } from "@/hooks/atlas/UseAtlasActions";
import { useAtlases } from "@/hooks/atlas/UseAtlases";
import { useAppStoreCalm } from "@/store/AppStore";
import { cn } from "@/utils/Cn";

const link = "flex items-center gap-1 text-gold hover:underline";

/** Saved atlases (PO's canvas): a row per known atlas with its map's picture and numbers; a click opens it, its ⋯
 * (or a right-click) opens its folder, renames or deletes it. */
export function AtlasesTab() {
	const app = useAppClient();
	const atlases = useAtlases();
	const state = useAppState().data;
	const actions = useAtlasActions();
	const s = useAppStoreCalm();
	const fail = (e: unknown) => s.showError(e);
	// the right-click menu: where, and for which atlas (user: "right click to open atlas folder")
	const [menu, setMenu] = useState<{ x: number; y: number; json: string; name: string } | null>(null);
	const rename = (json: string, name: string) =>
		s.ask({
			title: "Rename atlas",
			label: "Name in this list:",
			value: name,
			onOk: (n) => void app.renameAtlas(json, n).catch(fail),
		});
	const items = (json: string, name: string) => (
		<>
			<DropdownMenuItem onSelect={() => void app.showAtlasFolder(json).catch(fail)}>Open atlas folder</DropdownMenuItem>
			<DropdownMenuItem onSelect={() => rename(json, name)}>Rename…</DropdownMenuItem>
			<DropdownMenuSeparator />
			<DropdownMenuItem variant="destructive" onSelect={() => s.askDeleteAtlas(json)}>
				Delete…
			</DropdownMenuItem>
		</>
	);

	return (
		<div className="flex flex-col gap-3">
			<div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
				<button type="button" className={link} onClick={actions.askOpenFolder}>
					<PlusIcon className="size-3.5" aria-hidden />
					Add atlas (its screenshot folder)…
				</button>
				<button type="button" className={link} onClick={actions.askOpenAtlas}>
					Open atlas file…
				</button>
			</div>
			{!atlases.data?.length && (
				<p className="text-sm text-muted-foreground">No atlases yet: add your screenshot folder.</p>
			)}
			<ul className="flex flex-col gap-1.5">
				{atlases.data?.map((a) => (
					<li
						key={a.json}
						className={cn(
							"group/row flex items-center gap-3 rounded-md border p-1.5 pr-1 hover:bg-accent",
							a.open ? "border-gold/60 bg-accent/60" : "border-transparent",
						)}
					>
						<button
							type="button"
							className="flex min-w-0 flex-1 items-center gap-3 text-left"
							title={a.json}
							disabled={state?.busy}
							onClick={() => !a.open && void actions.openAtlas(a.json)}
							onContextMenu={(e) => {
								e.preventDefault();
								setMenu({ x: e.clientX, y: e.clientY, json: a.json, name: a.name });
							}}
						>
							{a.thumb ? (
								<img
									src={app.thumbUrl(a.json, state?.terrain_version ?? 0)}
									alt=""
									width={88}
									height={66}
									className="shrink-0 rounded"
								/>
							) : (
								<span className="flex h-[66px] w-[88px] shrink-0 items-center justify-center rounded bg-muted text-xs text-muted-foreground">
									no map yet
								</span>
							)}
							<span className="flex min-w-0 flex-col">
								<span className="flex items-center gap-1.5">
									<FolderOpenIcon
										className={cn("size-4 shrink-0", a.open ? "text-gold" : "text-muted-foreground")}
										aria-hidden
									/>
									<span className="truncate text-sm font-semibold">{a.name}</span>
								</span>
								<span className="text-xs text-muted-foreground">
									{a.numbers
										? `${a.numbers.maps} maps · ${a.numbers.icons} icons · ${a.numbers.shots} screenshots`
										: "reading…"}
								</span>
								{a.open && <span className="text-xs font-medium text-gold">open</span>}
							</span>
						</button>
						<DropdownMenu>
							<DropdownMenuTrigger asChild>
								<button
									type="button"
									aria-label={`More for ${a.name}`}
									title="Open its folder, rename, delete"
									className="rounded p-1.5 text-muted-foreground hover:bg-background hover:text-foreground"
								>
									<EllipsisIcon className="size-4" />
								</button>
							</DropdownMenuTrigger>
							<DropdownMenuContent align="end">{items(a.json, a.name)}</DropdownMenuContent>
						</DropdownMenu>
					</li>
				))}
			</ul>
			{menu && (
				<DropdownMenu open onOpenChange={(open) => !open && setMenu(null)}>
					<DropdownMenuTrigger asChild>
						<span className="pointer-events-none fixed size-px" style={{ left: menu.x, top: menu.y }} />
					</DropdownMenuTrigger>
					<DropdownMenuContent align="start">{items(menu.json, menu.name)}</DropdownMenuContent>
				</DropdownMenu>
			)}
		</div>
	);
}
