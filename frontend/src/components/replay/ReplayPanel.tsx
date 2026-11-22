import {
	DownloadIcon,
	PauseIcon,
	PlayIcon,
	SkipBackIcon,
	SkipForwardIcon,
	SquareIcon,
	StepBackIcon,
	StepForwardIcon,
	XIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { sameAtlas } from "@/api/Http";
import { Button } from "@/components/ui/button";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { Meta, ReplaySettings } from "@/domain/app/Meta";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useGeo } from "@/hooks/map/UseGeo";
import { useFrames } from "@/hooks/replay/UseFrames";
import { cameraTarget, counts, ease, stepFrom, stepsPerSecond } from "@/logic/Replay";
import {
	END_HOLD_MS,
	type ExportKind,
	GIF_FPS,
	GIF_MAX_FRAMES,
	GIF_WIDTH,
	mapIdle,
	nextFrames,
	onNextRender,
	ReplayExporter,
	VIDEO_FPS,
} from "@/logic/ReplayExport";
import { useAppStore } from "@/store/AppStore";
import { download } from "@/utils/Download";
import { Timeline } from "./Timeline";

/** The timelapse: play the atlas being made, screenshot by screenshot (or swept by area), with the camera following;
 * recorded as a video file. */
export function ReplayPanel({ meta }: { meta: Meta }) {
	const app = useAppClient();
	const replay = useAppStore((s) => s.replay);
	const patch = useAppStore((s) => s.patchReplay);
	const setReplay = useAppStore((s) => s.setReplay);
	const showError = useAppStore((s) => s.showError);
	const map = useAppStore((s) => s.map);
	const frames = useFrames(!!replay);
	const geo = useGeo();
	const last = useRef(0);
	const recorder = useRef<MediaRecorder | null>(null);
	const exporting = useRef<{ cancel: boolean } | null>(null);
	const [exportInfo, setExportInfo] = useState("");
	const [busy, setBusy] = useState(false); // a frame export runs: the position is its own (CodeRabbit)
	// settings changes, sent one after another (each answer then lands in order: CodeRabbit), and how many are still
	// on their way: no recording or export starts until they are done (an answer reset the panel while the recorder
	// ran: CodeRabbit)
	const queue = useRef<Promise<void>>(Promise.resolve());
	const [pending, setPending] = useState(0);
	const pendingNow = useRef(0);

	// playback: move on, move the camera
	// biome-ignore lint/correctness/useExhaustiveDependencies: restarted only when play starts / stops
	useEffect(() => {
		if (!replay?.playing || !map || !geo || !frames.data) return;
		let raf = 0;
		last.current = performance.now();
		const plan = replay.plan;
		const loop = (now: number) => {
			const dt = Math.min(0.25, (now - last.current) / 1000);
			last.current = now;
			const st = useAppStore.getState().replay;
			if (!st?.playing) return;
			const pos = Math.min(plan.n_steps, st.pos + dt * stepsPerSecond(plan));
			moveCamera(pos, ease(meta, plan.settings.smoothing, dt));
			const done = pos >= plan.n_steps;
			patch({ pos, playing: !done });
			if (done && recorder.current) recorder.current.stop();
			if (!done) raf = requestAnimationFrame(loop);
		};
		raf = requestAnimationFrame(loop);
		return () => cancelAnimationFrame(raf);
	}, [replay?.playing, map, geo, frames.data]);

	// whatever closes the timelapse (its X, the Timelapse tab, another atlas opened) or takes the panel away: a
	// recording stops and an export is cancelled (the tab's close left both running: CodeRabbit)
	const open = !!replay;
	useEffect(() => {
		if (!open) endCapture(recorder.current, exporting.current);
	}, [open]);
	useEffect(() => () => endCapture(recorder.current, exporting.current), []);

	if (!replay) return null;
	const { plan, pos } = replay;
	const st = plan.settings;
	const c = counts(plan, pos);

	function moveCamera(p: number, k: number) {
		if (!map || !geo || !frames.data || !replay) return;
		const box = cameraTarget(meta, replay.plan, frames.data, p);
		if (!box) return;
		const canvas = map.getCanvas();
		const [w, h] = [canvas.clientWidth, canvas.clientHeight];
		const tx = (box[0] + box[2]) / 2;
		const ty = (box[1] + box[3]) / 2;
		const px = Math.max(0.005, Math.min(w / Math.max(1, box[2] - box[0]), h / Math.max(1, box[3] - box[1])) * 0.96);
		const cc = map.getCenter();
		const [cx, cy] = geo.toAtlas(cc.lng, cc.lat);
		const cz = map.getZoom();
		const tz = geo.zoomFor(px);
		map.jumpTo({ center: geo.toLngLat(cx + (tx - cx) * k, cy + (ty - cy) * k), zoom: cz + (tz - cz) * k });
	}

	const seek = (p: number) => {
		if (exporting.current) return; // (a seek moved the export's frames)
		patch({ pos: p, playing: false });
		moveCamera(p, 1);
	};

	// one after another, so the last answer shown is the last change's, and a change that fails leaves the one before
	// it shown (an older answer arriving last showed its settings; with only the newest kept, a failing newer change
	// dropped an older one that had worked: CodeRabbit). None once the timelapse is closed (one opened it again).
	// (whether the app took it: a number box shows the setting again after a refusal)
	const change = (c: Partial<ReplaySettings>): Promise<boolean> => {
		const counted = (d: number) => {
			pendingNow.current += d;
			setPending(pendingNow.current);
		};
		counted(1);
		const run = queue.current.then(async () => {
			// (none sent while a recording or an export runs: they keep the plan they started with)
			if (!useAppStore.getState().replay || useAppStore.getState().replay?.recording) return false;
			try {
				const next = await app.setReplay(c);
				if (useAppStore.getState().replay) setReplay({ plan: next, pos: 0, playing: false, recording: false });
				return true;
			} catch (e) {
				showError(e);
				return false;
			}
		});
		queue.current = run.then(
			() => counted(-1),
			() => counted(-1),
		);
		return run;
	};

	const play = () => {
		if (exporting.current) return;
		if (replay.playing) return patch({ playing: false });
		patch({ pos: pos >= plan.n_steps ? 0 : pos, playing: true });
	};

	/**
	 * Export the replay as a GIF or a video, frame by frame: each frame waits until the map has drawn it, and gets a
	 * fixed time in the file, so it lasts the replay's length (the preview speed doesn't apply), as the old window's
	 * GIF export did. The last frame stays up for 2 s.
	 */
	const exportReplay = async (kind: ExportKind) => {
		if (!map || !geo || !frames.data || exporting.current || pendingNow.current) return;
		const fps = kind === "gif" ? GIF_FPS : VIDEO_FPS;
		const n = Math.max(2, Math.round(st.length * fps));
		const count = kind === "gif" ? Math.min(GIF_MAX_FRAMES, n) : n;
		const src = map.getCanvas();
		const W = kind === "gif" ? GIF_WIDTH : Number(st.video_width) || 1280;
		const H = Math.round((W * src.height) / Math.max(1, src.width));
		let ex: ReplayExporter;
		try {
			ex = new ReplayExporter(kind, W, H, fps);
		} catch (e) {
			showError(e);
			return;
		}
		const job = { cancel: false };
		exporting.current = job;
		setBusy(true);
		patch({ recording: true, playing: false });
		// it stops when the atlas or the map changes under it (it kept drawing the old map and threw: CodeRabbit), or
		// the timelapse it was made from is no longer the one open: checked here each time, not only by the cancel
		// the panel sets when it closes (an export finishing before that still downloaded: CodeRabbit)
		const still = sameAtlas();
		const live = () =>
			!job.cancel && still() && useAppStore.getState().map === map && useAppStore.getState().replay?.plan === plan;
		const frameMs = (st.length * 1000) / count;
		const k = ease(meta, st.smoothing, frameMs / 1000);
		try {
			for (let i = 0; i < count && live(); i++) {
				const p = (plan.n_steps * i) / (count - 1);
				patch({ pos: p });
				await nextFrames(); // the map's layers follow the new position
				moveCamera(p, i === 0 ? 1 : k);
				await mapIdle(map, 3000, i === 0 ? true : undefined); // (the first frame waits for the fog too)
				if (!live()) break;
				const cc = counts(plan, p);
				await onNextRender(map, (canvas) =>
					ex.draw(canvas, {
						text: `${cc.when} · screenshots ${cc.shots} / ${plan.step_of.length} · maps ${cc.maps}`,
						colour: meta.colours.sessions[cc.session % meta.colours.sessions.length],
					}),
				);
				ex.add(i === count - 1 ? frameMs + END_HOLD_MS : frameMs);
				setExportInfo(`exporting ${kind === "gif" ? "GIF" : "video"}: frame ${i + 1} / ${count}`);
			}
			const file = live() ? await ex.finish() : null;
			// checked again after finishing: the video's flush is a wait, and a cancel or an atlas switch during it
			// still downloaded it (CodeRabbit)
			if (file && live()) download(file, kind === "gif" ? "atlas-timelapse.gif" : "atlas-timelapse.webm");
			else if (!job.cancel) showError("The export stopped: the atlas changed while it ran.");
		} catch (e) {
			if (live())
				showError(e); // (a map replaced meanwhile: said above, not as an error)
			else if (!job.cancel) showError("The export stopped: the atlas changed while it ran.");
		} finally {
			ex.close();
			exporting.current = null;
			setBusy(false);
			setExportInfo("");
			// (only for its own timelapse: a new one opened meanwhile had its recording flag cleared: CodeRabbit)
			if (still() && useAppStore.getState().replay?.plan === plan) patch({ recording: false });
		}
	};

	const stopRecording = () => {
		if (recorder.current) recorder.current.stop();
		if (exporting.current) exporting.current.cancel = true;
	};

	const record = () => {
		if (!map || pendingNow.current) return;
		if (recorder.current) {
			recorder.current.stop();
			return;
		}
		const canvas = map.getCanvas();
		if (!("captureStream" in canvas) || typeof MediaRecorder === "undefined")
			return showError("This browser can't record the map (no MediaRecorder).");
		const stream = canvas.captureStream(30);
		const type = MediaRecorder.isTypeSupported("video/webm;codecs=vp9") ? "video/webm;codecs=vp9" : "video/webm";
		const rec = new MediaRecorder(stream, { mimeType: type, videoBitsPerSecond: 8_000_000 });
		const chunks: Blob[] = [];
		rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
		rec.onstop = () => {
			recorder.current = null;
			patch({ recording: false, playing: false });
			download(new Blob(chunks, { type: "video/webm" }), "atlas-timelapse.webm");
		};
		recorder.current = rec;
		rec.start(250);
		patch({ recording: true, pos: 0, playing: true });
		moveCamera(0, 1);
	};

	const close = async () => {
		setReplay(null); // (a recording and an export end with it: above)
		await app.closeReplay().catch(showError);
	};

	const sel = (label: string, key: keyof ReplaySettings, values: string[], disabled = false) => (
		<div className="flex items-center gap-1.5 text-xs">
			<span className="text-muted-foreground">{label}</span>
			<Select
				value={String(st[key])}
				onValueChange={(v) => void change({ [key]: v })}
				disabled={disabled || replay.recording}
			>
				<SelectTrigger size="sm" aria-label={label}>
					<SelectValue />
				</SelectTrigger>
				<SelectContent>
					{values.map((v) => (
						<SelectItem key={v} value={v}>
							{v}
						</SelectItem>
					))}
				</SelectContent>
			</Select>
		</div>
	);

	const num = (label: string, key: "length" | "per_step", lo: number, hi: number) => (
		<NumberSetting
			label={label}
			value={st[key]}
			lo={lo}
			hi={hi}
			whole={key === "per_step"}
			disabled={replay.recording}
			onCommit={(v) => change({ [key]: v })}
		/>
	);

	return (
		// under the map, not over it (user: the panel hid the map); the map gets the rest of the height
		<div className="poe-panel z-20 flex shrink-0 flex-col gap-2 p-3">
			<div className="flex items-center gap-2">
				{/* start, a step back, play, a step on, the end (user: there was no jump to the start) */}
				<Button
					size="icon-sm"
					variant="outline"
					aria-label="To the start"
					title="To the start"
					disabled={busy}
					onClick={() => seek(0)}
				>
					<SkipBackIcon />
				</Button>
				<Button
					size="icon-sm"
					variant="outline"
					aria-label="Step back"
					title="Step back"
					disabled={busy}
					onClick={() => seek(stepFrom(pos, -1, plan))}
				>
					<StepBackIcon />
				</Button>
				<Button size="icon-sm" aria-label={replay.playing ? "Pause" : "Play"} disabled={busy} onClick={play}>
					{replay.playing ? <PauseIcon /> : <PlayIcon />}
				</Button>
				<Button
					size="icon-sm"
					variant="outline"
					aria-label="Step forward"
					title="Step forward"
					disabled={busy}
					onClick={() => seek(stepFrom(pos, 1, plan))}
				>
					<StepForwardIcon />
				</Button>
				<Button
					size="icon-sm"
					variant="outline"
					aria-label="To the end"
					title="To the end"
					disabled={busy}
					onClick={() => seek(plan.n_steps)}
				>
					<SkipForwardIcon />
				</Button>
				<span className="flex items-center gap-2 font-mono text-xs">
					<span
						className="size-2.5 rounded-full"
						style={{ background: meta.colours.sessions[c.session % meta.colours.sessions.length] }}
					/>
					{c.when} · screenshots {c.shots} / {plan.step_of.length} · maps {c.maps}
				</span>
				<span className="flex-1" />
				{exportInfo && <span className="text-xs text-gold">{exportInfo}</span>}
				{replay.recording ? (
					<Button size="xs" variant="destructive" onClick={stopRecording}>
						<SquareIcon />
						{exporting.current ? "Cancel export" : "Stop and save"}
					</Button>
				) : (
					// one Export with both kinds (user: the old window exported GIFs, the page only recorded video)
					<DropdownMenu>
						<DropdownMenuTrigger asChild>
							<Button
								size="xs"
								variant="outline"
								disabled={pending > 0}
								title={pending > 0 ? "Wait until the settings changed are saved" : undefined}
							>
								<DownloadIcon />
								Export
							</Button>
						</DropdownMenuTrigger>
						<DropdownMenuContent align="end">
							<DropdownMenuItem onSelect={() => void exportReplay("gif")}>
								GIF ({GIF_FPS} fps, {GIF_WIDTH} px wide, lasts the length setting)
							</DropdownMenuItem>
							<DropdownMenuItem onSelect={() => void exportReplay("video")}>
								Video (.webm, {VIDEO_FPS} fps, lasts the length setting)
							</DropdownMenuItem>
							<DropdownMenuItem onSelect={record}>Record the screen as it plays (.webm)</DropdownMenuItem>
						</DropdownMenuContent>
					</DropdownMenu>
				)}
				<Button size="icon-sm" variant="ghost" aria-label="Close the replay" onClick={() => void close()}>
					<XIcon />
				</Button>
			</div>
			<Timeline plan={plan} pos={pos} sessions={meta.colours.sessions} onSeek={seek} />
			<div className="flex flex-wrap items-center gap-3">
				{sel("order", "type", meta.replay.types)}
				{sel("reveal", "reveal", meta.replay.reveals, st.type === "by time")}
				{sel("camera", "camera", meta.replay.cameras)}
				{sel("smoothing", "smoothing", Object.keys(meta.replay.smoothing))}
				{num("length (s)", "length", 3, 600)}
				{num("per step", "per_step", 1, 50)}
				<div className="flex items-center gap-1.5 text-xs">
					<span className="text-muted-foreground">speed</span>
					<Select
						value={String(st.speed)}
						onValueChange={(v) => void change({ speed: Number(v) })}
						disabled={replay.recording} // as every other setting here (CodeRabbit)
					>
						<SelectTrigger size="sm" aria-label="speed">
							<SelectValue />
						</SelectTrigger>
						<SelectContent>
							{meta.replay.speeds.map((v) => (
								<SelectItem key={v} value={String(v)}>
									{v}x
								</SelectItem>
							))}
						</SelectContent>
					</Select>
				</div>
				{plan.real && (
					<span className="text-xs text-muted-foreground">
						(= {plan.real}, x{Math.round(plan.real_seconds / Math.max(1, st.length))})
					</span>
				)}
			</div>
		</div>
	);
}

/** A moment after the last key before a number typed is used. */
const NUMBER_SETTLE_MS = 500;

/** Stop a screen recording still running and cancel a frame export (each only once: a stopped recorder throws). */
function endCapture(recorder: MediaRecorder | null, exporting: { cancel: boolean } | null) {
	if (recorder?.state === "recording") recorder.stop();
	if (exporting) exporting.cancel = true;
}

/**
 * A number setting typed in a box: used a moment after you stop typing, at once on Enter or on leaving the box (user:
 * the timelapse's length only changed once the box lost focus, Enter did nothing), kept within lo..hi; shows the
 * setting as it is again when the app changes it (unless being typed in).
 */
export function NumberSetting({
	label,
	value,
	lo,
	hi,
	whole = false,
	disabled = false,
	onCommit,
}: {
	label: string;
	value: number;
	lo: number;
	hi: number;
	whole?: boolean;
	disabled?: boolean;
	/** Use a value; it may answer whether it was taken (refused: the box shows the setting again). */
	onCommit: (v: number) => Promise<boolean> | undefined;
}) {
	const [text, setText] = useState(String(value));
	const typing = useRef(false);
	const edits = useRef(0); // keys typed: a refusal answered after newer typing leaves the box as typed
	const current = useRef(value);
	current.current = value;
	// a value sent and still on its way: a new one is compared with it, not the setting in use (typed back to the
	// setting while another was on its way, it was never sent and the other won: CodeRabbit)
	const sent = useRef<number | null>(null);
	const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined); // a value still settling
	const off = useRef(disabled);
	off.current = disabled;
	useEffect(() => {
		if (!typing.current) setText(String(value));
	}, [value]);
	// disabled (a recording started): a value still settling is dropped and the box shows the setting (it was sent
	// anyway and reset the replay: CodeRabbit)
	useEffect(() => {
		if (!disabled) return;
		clearTimeout(timer.current);
		typing.current = false;
		setText(String(value));
	}, [disabled, value]);
	// Enter or leaving the box: what was typed, kept within its range (an empty or wrong box goes back)
	const commit = (t: string) => {
		clearTimeout(timer.current); // (sent now: not again once it would have settled)
		typing.current = false;
		if (off.current) return setText(String(value));
		const n = Number(t);
		if (t.trim() === "" || !Number.isFinite(n)) return setText(String(value));
		const v = Math.min(hi, Math.max(lo, whole ? Math.round(n) : n));
		setText(String(v));
		if (v !== (sent.current ?? value)) send(v);
	};
	// a value used; refused, and nothing typed since, the box shows the setting in use again (it kept the refused
	// number while the replay used the old one: CodeRabbit)
	const send = (v: number) => {
		const at = edits.current;
		const answer = onCommit(v);
		if (answer) {
			sent.current = v;
			void answer.then((ok) => {
				if (sent.current === v) sent.current = null;
				if (ok || edits.current !== at) return;
				typing.current = false;
				setText(String(current.current));
			});
		}
	};
	// typing paused: used only when it is already a number in range; the box is left as typed (a half-typed "2" on
	// the way to "20" was set to the lowest and written over: self review)
	const settle = (t: string) => {
		if (off.current) return;
		const n = Number(t);
		const v = whole ? Math.round(n) : n;
		if (t.trim() !== "" && Number.isFinite(n) && v >= lo && v <= hi && v !== (sent.current ?? value)) send(v);
	};
	// (the one as it is then: the setting may have changed meanwhile)
	const latest = useRef(settle);
	latest.current = settle;
	useEffect(() => {
		if (!typing.current) return;
		timer.current = setTimeout(() => latest.current(text), NUMBER_SETTLE_MS);
		return () => clearTimeout(timer.current);
	}, [text]);
	return (
		<div className="flex items-center gap-1.5 text-xs">
			<span className="text-muted-foreground">{label}</span>
			<Input
				aria-label={label}
				type="number"
				min={lo}
				max={hi}
				value={text}
				disabled={disabled}
				className="h-7 w-20 px-1.5"
				onChange={(e) => {
					typing.current = true;
					edits.current++;
					setText(e.target.value);
				}}
				onKeyDown={(e) => {
					if (e.key === "Enter") commit(text);
				}}
				onBlur={() => typing.current && commit(text)}
			/>
		</div>
	);
}
