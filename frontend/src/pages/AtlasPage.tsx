import { type DragEvent, useState } from "react";
import { ProgressBox } from "@/components/common/ProgressBox";
import { BookmarkDialog } from "@/components/dialogs/BookmarkDialog";
import { ConfirmDialog } from "@/components/dialogs/ConfirmDialog";
import { DeleteAtlasDialog } from "@/components/dialogs/DeleteAtlasDialog";
import { FileBrowserDialog } from "@/components/dialogs/FileBrowserDialog";
import { GroupDialog } from "@/components/dialogs/GroupDialog";
import { PromptDialog } from "@/components/dialogs/PromptDialog";
import { QuestionDialog } from "@/components/dialogs/QuestionDialog";
import { KeepDialog } from "@/components/dialogs/KeepDialog";
import { RecheckDialog } from "@/components/dialogs/RecheckDialog";
import { SourcesDialog } from "@/components/dialogs/SourcesDialog";
import { MapImageWait } from "@/components/layout/MapImageWait";
import { SidePanel } from "@/components/layout/SidePanel";
import { SideReveal } from "@/components/layout/SideReveal";
import { StatusBar } from "@/components/layout/StatusBar";
import { TopBar } from "@/components/layout/TopBar";
import { AtlasMap } from "@/components/map/AtlasMap";
import { MapNotes } from "@/components/map/MapNotes";
import { ReplayPanel } from "@/components/replay/ReplayPanel";
import { TimelapseTab } from "@/components/replay/TimelapseTab";
import { Button } from "@/components/ui/button";
import { useAppState } from "@/hooks/app/UseAppState";
import { useEventStream } from "@/hooks/app/UseEventStream";
import { useMeta } from "@/hooks/app/UseMeta";
import { usePageLog } from "@/hooks/app/UsePageLog";
import { useAtlasActions } from "@/hooks/atlas/UseAtlasActions";

/** The app's one page: top bar, side panel, the map, the status line, and the dialogs. */
export function AtlasPage() {
	const connected = useEventStream();
	usePageLog();
	const state = useAppState();
	const meta = useMeta();
	const actions = useAtlasActions();
	const [dragging, setDragging] = useState(false);

	if (state.isError || meta.isError)
		return (
			<div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
				<h1 className="text-lg font-semibold text-gold">The app isn't running</h1>
				<p className="text-muted-foreground">
					Start it again (python -m grand_project, or the start script), then reload this page.
				</p>
				<Button onClick={() => window.location.reload()}>Reload</Button>
			</div>
		);
	if (!state.data || !meta.data) return <div className="p-8 text-muted-foreground">Loading…</div>;
	const s = state.data;
	const map = s.map;
	// a new map image grid (another atlas, a rebuilt map image) makes a new map
	const mapKey = map ? `${s.atlas?.path}|${JSON.stringify(map.grid)}|${map.zmax}` : "";

	const onDrop = (e: DragEvent) => {
		e.preventDefault();
		setDragging(false);
		void actions.dropFiles([...e.dataTransfer.files]);
	};

	return (
		<div className="flex h-full flex-col">
			<TopBar />
			<div className="flex min-h-0 flex-1">
				{/* hidden: its reveal button on the map's edge brings it back (user's notes: a hideable sidebar) */}
				{!s.settings.ui.side_hidden && <SidePanel debug={s.debug} />}
				<main
					className={`flex min-w-0 flex-1 flex-col bg-black ${s.settings.ui.side === "right" ? "-order-1" : ""}`}
					onDragOver={(e) => {
						e.preventDefault();
						setDragging(true);
					}}
					onDragLeave={() => setDragging(false)}
					onDrop={onDrop}
				>
					<div className="relative min-h-0 flex-1">
						{map ? (
							<AtlasMap key={mapKey} info={map} meta={meta.data} />
						) : (
							<div className="flex h-full flex-col items-center justify-center gap-3 text-center text-muted-foreground">
								{!s.atlas && s.opening ? (
									<p>Loading atlas {s.opening}…</p>
								) : s.atlas ? (
									s.atlas.shots ? (
										<MapImageWait />
									) : (
										<>
											<p>This atlas has no screenshots yet.</p>
											<Button onClick={actions.askAddScreenshots}>Add screenshots…</Button>
											<p className="text-xs">or drop screenshot files here, or turn on Auto-add</p>
										</>
									)
								) : (
									<>
										<p>No atlas open.</p>
										<div className="flex gap-2">
											<Button onClick={actions.askOpenFolder}>Open your screenshot folder…</Button>
											<Button variant="outline" onClick={actions.askNewAtlas}>
												New atlas…
											</Button>
										</div>
									</>
								)}
							</div>
						)}
						<ProgressBox text={s.progress} />
						<MapNotes />
						{map && <TimelapseTab />}
						{s.settings.ui.side_hidden && (
							<SideReveal
								className={`absolute top-1/2 z-20 -translate-y-1/2 ${s.settings.ui.side === "right" ? "-right-[5px]" : "-left-[5px]"}`}
							/>
						)}
						{dragging && (
							<div className="pointer-events-none absolute inset-3 z-30 flex items-center justify-center rounded-lg border-2 border-dashed border-gold bg-black/40 text-gold">
								Drop screenshots: one is placed by hand, several are added
							</div>
						)}
					</div>
					<ReplayPanel meta={meta.data} />
				</main>
			</div>
			<StatusBar connected={connected} />
			<QuestionDialog />
			<FileBrowserDialog />
			<PromptDialog />
			<ConfirmDialog />
			<RecheckDialog />
			<KeepDialog />
			<BookmarkDialog />
			<GroupDialog />
			<SourcesDialog />
			<DeleteAtlasDialog />
		</div>
	);
}
