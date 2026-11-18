import { PauseIcon, PlayIcon, SkipBackIcon, SkipForwardIcon, SquareIcon, VideoIcon, XIcon } from "lucide-react";
import { useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { Meta, ReplaySettings } from "@/domain/app/Meta";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useGeo } from "@/hooks/map/UseGeo";
import { useFrames } from "@/hooks/replay/UseFrames";
import { cameraTarget, counts, ease, stepFrom, stepsPerSecond } from "@/logic/Replay";
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

	// playback: move on, move the camera
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
		// biome-ignore lint/correctness/useExhaustiveDependencies: restarted only when play starts / stops
	}, [replay?.playing, map, geo, frames.data]);

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
		patch({ pos: p, playing: false });
		moveCamera(p, 1);
	};

	const change = async (c: Partial<ReplaySettings>) => {
		try {
			const next = await app.setReplay(c);
			setReplay({ plan: next, pos: 0, playing: false, recording: false });
		} catch (e) {
			showError(e);
		}
	};

	const play = () => {
		if (replay.playing) return patch({ playing: false });
		patch({ pos: pos >= plan.n_steps ? 0 : pos, playing: true });
	};

	const record = () => {
		if (!map) return;
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
		recorder.current?.stop();
		setReplay(null);
		await app.closeReplay().catch(showError);
	};

	const sel = (label: string, key: keyof ReplaySettings, values: string[], disabled = false) => (
		<label className="flex items-center gap-1.5 text-xs">
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
		</label>
	);

	const num = (label: string, key: "length" | "per_step", lo: number, hi: number) => (
		<label className="flex items-center gap-1.5 text-xs">
			<span className="text-muted-foreground">{label}</span>
			<Input
				aria-label={label}
				type="number"
				min={lo}
				max={hi}
				defaultValue={st[key]}
				key={`${key}-${st[key]}`}
				disabled={replay.recording}
				className="h-7 w-16"
				onBlur={(e) => {
					const v = Math.min(hi, Math.max(lo, Number(e.target.value) || st[key]));
					if (v !== st[key]) void change({ [key]: key === "per_step" ? Math.round(v) : v });
				}}
			/>
		</label>
	);

	return (
		// under the map, not over it (user: the panel hid the map); the map gets the rest of the height
		<div className="z-20 flex shrink-0 flex-col gap-2 border-t bg-card p-3">
			<div className="flex items-center gap-2">
				<Button size="icon-sm" variant="outline" aria-label="Step back" onClick={() => seek(stepFrom(pos, -1, plan))}>
					<SkipBackIcon />
				</Button>
				<Button size="icon-sm" aria-label={replay.playing ? "Pause" : "Play"} onClick={play}>
					{replay.playing ? <PauseIcon /> : <PlayIcon />}
				</Button>
				<Button size="icon-sm" variant="outline" aria-label="Step forward" onClick={() => seek(stepFrom(pos, 1, plan))}>
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
				<Button size="xs" variant={replay.recording ? "destructive" : "outline"} onClick={record}>
					{replay.recording ? <SquareIcon /> : <VideoIcon />}
					{replay.recording ? "Stop recording" : "Record video"}
				</Button>
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
				<label className="flex items-center gap-1.5 text-xs">
					<span className="text-muted-foreground">speed</span>
					<Select value={String(st.speed)} onValueChange={(v) => void change({ speed: Number(v) })}>
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
				</label>
				{plan.real && (
					<span className="text-xs text-muted-foreground">
						(= {plan.real}, x{Math.round(plan.real_seconds / Math.max(1, st.length))})
					</span>
				)}
			</div>
		</div>
	);
}
