import { PencilIcon, RefreshCwIcon, Trash2Icon } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
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

/** Saved atlases: a card per known atlas (its map, maps / icons / screenshots); click one to open it, right-click it
 * to open its folder, rename or delete it. */
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

	return (
		<div className="flex flex-col gap-3">
			<div className="flex flex-wrap gap-1.5">
				<Button size="xs" onClick={actions.askOpenFolder}>
					Add atlas (its screenshot folder)…
				</Button>
				<Button size="xs" variant="outline" onClick={actions.askOpenAtlas}>
					Open atlas file…
				</Button>
			</div>
			{!atlases.data?.length && <p className="text-muted-foreground">No atlases yet: add your screenshot folder.</p>}
			{atlases.data?.map((a) => (
				<div
					key={a.json}
					className={cn("flex gap-3 rounded-md border p-2 hover:bg-accent", a.open && "border-gold bg-accent/60")}
				>
					<button
						type="button"
						className="flex flex-1 gap-3 text-left"
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
								width={112}
								height={84}
								className="rounded"
							/>
						) : (
							<div className="flex h-[84px] w-[112px] items-center justify-center rounded bg-muted text-xs text-muted-foreground">
								no map yet
							</div>
						)}
						<div className="flex min-w-0 flex-col">
							<span className="truncate font-semibold">{a.name}</span>
							<span className="text-xs text-muted-foreground">
								{a.numbers
									? `${a.numbers.maps} maps · ${a.numbers.icons} icons · ${a.numbers.shots} screenshots`
									: "reading…"}
							</span>
							{a.open && <span className="text-xs text-gold">open</span>}
						</div>
					</button>
					<div className="flex flex-col gap-1">
						<Button
							size="icon-sm"
							variant="ghost"
							aria-label={`Rename ${a.name}`}
							onClick={() => rename(a.json, a.name)}
						>
							<PencilIcon />
						</Button>
						<Button
							size="icon-sm"
							variant="ghost"
							aria-label={`Re-check ${a.name}`}
							title={a.open ? "Re-check this atlas" : "Open and re-check this atlas"}
							disabled={state?.busy || a.numbers?.shots === 0}
							onClick={() => s.askRecheck(a.json)}
						>
							<RefreshCwIcon />
						</Button>
						<Button
							size="icon-sm"
							variant="ghost"
							aria-label={`Delete ${a.name}`}
							onClick={() => s.askDeleteAtlas(a.json)}
						>
							<Trash2Icon />
						</Button>
					</div>
				</div>
			))}
			{menu && (
				<DropdownMenu open onOpenChange={(open) => !open && setMenu(null)}>
					<DropdownMenuTrigger asChild>
						<span className="pointer-events-none fixed size-px" style={{ left: menu.x, top: menu.y }} />
					</DropdownMenuTrigger>
					<DropdownMenuContent align="start">
						<DropdownMenuItem onSelect={() => void app.showAtlasFolder(menu.json).catch(fail)}>
							Open atlas folder
						</DropdownMenuItem>
						<DropdownMenuItem onSelect={() => rename(menu.json, menu.name)}>Rename…</DropdownMenuItem>
						<DropdownMenuSeparator />
						<DropdownMenuItem variant="destructive" onSelect={() => s.askDeleteAtlas(menu.json)}>
							Delete…
						</DropdownMenuItem>
					</DropdownMenuContent>
				</DropdownMenu>
			)}
		</div>
	);
}
