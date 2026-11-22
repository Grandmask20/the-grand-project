import { useQueryClient } from "@tanstack/react-query";
import { ClapperboardIcon, LassoIcon, MenuIcon, RouteIcon, Undo2Icon, XIcon } from "lucide-react";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { sameAtlas } from "@/api/Http";
import tablet from "@/assets/tablet.png";
import { Button } from "@/components/ui/button";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuSeparator,
	DropdownMenuSub,
	DropdownMenuSubContent,
	DropdownMenuSubTrigger,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import { useAtlasActions } from "@/hooks/atlas/UseAtlasActions";
import { useAtlases } from "@/hooks/atlas/UseAtlases";
import { useAppStoreCalm } from "@/store/AppStore";
import { UpdateButton } from "./UpdateButton";

/** The File and Atlas menus, and the buttons used most (undo, city biome lasso, replay). */
export function TopBar() {
	const app = useAppClient();
	const queryClient = useQueryClient();
	const state = useAppState().data;
	const atlases = useAtlases();
	const actions = useAtlasActions();
	const s = useAppStoreCalm();
	const fail = (e: unknown) => s.showError(e);
	const open = !!state?.atlas;
	const busy = !!state?.busy;
	const refresh = () => queryClient.invalidateQueries({ queryKey: AppQueryKeys.state });
	// while adding runs it doesn't start: cancel, or queue it to start once adding is done (you)
	// the box and its Queue are for the atlas Fix seams was asked for: another opened meanwhile, nothing is queued
	// for it (the Queue went out with the new atlas's generation: CodeRabbit)
	const fixSeams = () => {
		const same = sameAtlas();
		return app
			.fixSeams()
			.then((r) => {
				if (!same()) return;
				if (r.adding)
					s.askConfirm({
						title: "Fix seams",
						text: "Adding is running. Fix seams can start once it is done (Stop fixing seams takes it off the queue).",
						yes: "Queue",
						onYes: () => {
							if (same()) void app.fixSeams(true).then(refresh).catch(fail);
						},
					});
				else void refresh();
			})
			.catch(fail);
	};

	const openReplay = async () => {
		if (s.replay) {
			s.setReplay(null);
			await app.closeReplay().catch(fail);
			return;
		}
		try {
			const plan = await app.openReplay();
			s.setReplay({ plan, pos: plan.n_steps, playing: false, recording: false });
		} catch (e) {
			fail(e);
		}
	};

	const undo = () =>
		s.askConfirm({
			title: "Undo last add",
			text: `Remove the screenshot(s) added last?\n\n${(state?.undo.at(-1) ?? []).join("\n")}`,
			yes: "Undo",
			onYes: () => void app.undo().catch(fail),
		});

	return (
		<header className="flex h-11 shrink-0 items-center gap-1.5 border-b bg-card px-2">
			<span className="mr-2 flex shrink-0 items-center gap-1.5 font-semibold tracking-wide whitespace-nowrap text-gold">
				{/* the in-game tablet the program is named after (user) */}
				<img src={tablet} alt="" className="size-7" />
				The Grand Project
			</span>
			<DropdownMenu>
				<DropdownMenuTrigger asChild>
					<Button size="sm" variant="ghost">
						<MenuIcon />
						File
					</Button>
				</DropdownMenuTrigger>
				<DropdownMenuContent align="start" className="w-64">
					<DropdownMenuItem onSelect={actions.askNewAtlas}>New atlas…</DropdownMenuItem>
					<DropdownMenuItem onSelect={actions.askOpenAtlas}>Open atlas…</DropdownMenuItem>
					<DropdownMenuItem onSelect={actions.askOpenFolder}>Open a screenshot folder…</DropdownMenuItem>
					<DropdownMenuSeparator />
					<DropdownMenuItem disabled={busy} onSelect={actions.askAddScreenshots}>
						Add screenshots…
					</DropdownMenuItem>
					<DropdownMenuItem disabled={!open} onSelect={actions.askPlaceByHand}>
						Place a screenshot by hand…
					</DropdownMenuItem>
					<DropdownMenuSeparator />
					<DropdownMenuItem disabled={!open} onSelect={() => void app.saveAtlas().catch(fail)}>
						Save
					</DropdownMenuItem>
					<DropdownMenuItem disabled={!open || !state?.atlas?.shots} onSelect={() => void app.exportPngs().catch(fail)}>
						Export map PNGs
					</DropdownMenuItem>
					<DropdownMenuItem
						disabled={!open || busy || !state?.atlas?.shots}
						onSelect={() => state?.atlas && s.askRecheck(state.atlas.path)}
					>
						Re-check the whole atlas
					</DropdownMenuItem>
					{state?.seams ? (
						<DropdownMenuItem onSelect={() => void app.stopSeams().catch(fail)}>Stop fixing seams</DropdownMenuItem>
					) : (
						<DropdownMenuItem disabled={!open || !state?.atlas?.shots} onSelect={() => void fixSeams()}>
							Fix seams (clean map)
						</DropdownMenuItem>
					)}
					<DropdownMenuSeparator />
					<DropdownMenuItem disabled={!open || busy} onSelect={() => void actions.closeAtlas()}>
						Close atlas
					</DropdownMenuItem>
					<DropdownMenuItem
						onSelect={() =>
							s.askConfirm({
								title: "Quit",
								text: busy
									? "Screenshots are still being processed: the step in progress is finished and saved first. Quit?"
									: "Save and quit the app? (This page stops working until you start it again.)",
								yes: "Quit",
								onYes: () => void app.quit().catch(fail),
							})
						}
					>
						Quit the app
					</DropdownMenuItem>
				</DropdownMenuContent>
			</DropdownMenu>
			<DropdownMenu>
				<DropdownMenuTrigger asChild>
					<Button size="sm" variant="ghost">
						{state?.atlas ? `Atlas: ${state.atlas.name}` : "Atlas"} ▾
					</Button>
				</DropdownMenuTrigger>
				<DropdownMenuContent align="start" className="w-64">
					{atlases.data?.map((a) => (
						<DropdownMenuSub key={a.json}>
							<DropdownMenuSubTrigger>{(a.open ? "● " : "   ") + a.name}</DropdownMenuSubTrigger>
							<DropdownMenuSubContent>
								<DropdownMenuItem disabled={a.open || busy} onSelect={() => void actions.openAtlas(a.json)}>
									Open
								</DropdownMenuItem>
								<DropdownMenuItem
									disabled={busy}
									onSelect={() => void actions.openFolder(a.json.replace(/[\\/][^\\/]*$/, ""))}
								>
									Add new screenshots from its folder
								</DropdownMenuItem>
								<DropdownMenuItem
									onSelect={() =>
										s.ask({
											title: "Rename atlas",
											label: "Name in this list:",
											value: a.name,
											onOk: (n) => void app.renameAtlas(a.json, n).catch(fail),
										})
									}
								>
									Rename…
								</DropdownMenuItem>
								<DropdownMenuItem onSelect={() => s.askDeleteAtlas(a.json)}>Remove / delete…</DropdownMenuItem>
							</DropdownMenuSubContent>
						</DropdownMenuSub>
					))}
					{!!atlases.data?.length && <DropdownMenuSeparator />}
					<DropdownMenuItem onSelect={actions.askOpenFolder}>
						Add new atlas… (choose its screenshot folder)
					</DropdownMenuItem>
				</DropdownMenuContent>
			</DropdownMenu>
			<span className="mx-1 h-5 w-px bg-border" />
			<Button size="sm" variant="ghost" disabled={!state?.undo.length || busy} onClick={undo} title="Undo last add">
				<Undo2Icon />
				Undo
			</Button>
			{/* on: the button ends it (user: only Esc did, nothing on screen said so); none while the timelapse is open */}
			<Button
				size="sm"
				variant={s.mode.kind === "lasso" ? "default" : "ghost"}
				disabled={!open || !!s.replay}
				onClick={() => s.setMode(s.mode.kind === "lasso" ? { kind: "normal" } : { kind: "lasso" })}
				title="Set the biome of maps (a city type, a Breach stronghold, or none): draw around them"
			>
				{s.mode.kind === "lasso" ? <XIcon /> : <LassoIcon />}
				{/* (not "City biome": strongholds aren't cities, user) */}
				{s.mode.kind === "lasso" ? "End biome select" : "Biome select"}
			</Button>
			<Button
				size="sm"
				variant={s.replay ? "default" : "ghost"}
				disabled={!state?.atlas?.shots}
				onClick={() => void openReplay()}
				title="Replay: the atlas being made, as a timelapse"
			>
				<ClapperboardIcon />
				Replay
			</Button>
			{/* a route between two maps you click: track it, or save it with the bookmarks (user) */}
			<Button
				size="sm"
				variant={s.mode.kind === "route" ? "default" : "ghost"}
				disabled={!state?.atlas || !!s.replay}
				onClick={() => s.setMode(s.mode.kind === "route" ? { kind: "normal" } : { kind: "route", from: null })}
				title="Route: click the map it starts from, then the one it goes to"
			>
				{s.mode.kind === "route" ? <XIcon /> : <RouteIcon />}
				{s.mode.kind === "route" ? "End route" : "Route"}
			</Button>
			<span className="flex-1" />
			{state?.atlas && (
				<span className="truncate text-xs text-muted-foreground" title={state.atlas.path}>
					{state.atlas.maps} maps · {state.atlas.icons} icons · {state.atlas.landmarks} landmarks · {state.atlas.shots}{" "}
					screenshots
				</span>
			)}
			{/* the version, and whether it is the latest (user's mockup: as Path of Building's update corner) */}
			<UpdateButton />
		</header>
	);
}
