import { useRef } from "react";
import type { ReplayPlan } from "@/domain/replay/ReplayPlan";
import { seekAt } from "@/logic/Replay";

/** The replay's timeline: a band coloured by session, a tick where each batch starts, the head; click or drag to
 * seek. */
export function Timeline({
	plan,
	pos,
	sessions,
	onSeek,
}: {
	plan: ReplayPlan;
	pos: number;
	sessions: string[];
	onSeek: (pos: number) => void;
}) {
	const box = useRef<HTMLDivElement>(null);
	const n = Math.max(1, plan.n_steps);
	const colour = (k: number) => sessions[k % Math.max(1, sessions.length)] ?? "#888";

	const bands: { from: number; to: number; session: number }[] = [];
	let start = 0;
	for (let s = 1; s <= n; s++) {
		if (s === n || plan.step_session[s] !== plan.step_session[start]) {
			bands.push({ from: start, to: s, session: plan.step_session[start] ?? 0 });
			start = s;
		}
	}

	const seek = (clientX: number) => {
		const r = box.current?.getBoundingClientRect();
		if (r) onSeek(seekAt(clientX, r.left, r.width, plan.n_steps));
	};

	return (
		<div
			ref={box}
			role="slider"
			tabIndex={0}
			aria-label="Replay position"
			aria-valuemin={0}
			aria-valuemax={plan.n_steps}
			aria-valuenow={Math.round(pos)}
			className="relative h-7 cursor-pointer select-none"
			onPointerDown={(e) => {
				(e.target as HTMLElement).setPointerCapture?.(e.pointerId);
				seek(e.clientX);
			}}
			onPointerMove={(e) => {
				if (e.buttons & 1) seek(e.clientX);
			}}
			onKeyDown={(e) => {
				if (e.key === "ArrowLeft") onSeek(Math.max(0, pos - n / 100));
				if (e.key === "ArrowRight") onSeek(Math.min(n, pos + n / 100));
			}}
		>
			{bands.map((b) => (
				<div
					key={b.from}
					className="absolute top-3 h-1 rounded-sm"
					style={{
						left: `${(b.from / n) * 100}%`,
						width: `${((b.to - b.from) / n) * 100}%`,
						background: colour(b.session),
					}}
				/>
			))}
			{plan.ticks.map((t) => (
				<div
					key={t}
					className="absolute top-1.5 h-4 w-0.5"
					style={{ left: `${(t / n) * 100}%`, background: colour(plan.step_session[t] ?? 0) }}
				/>
			))}
			<div
				className="absolute top-0.5 h-6 w-2 -translate-x-1 rounded-sm border border-map bg-gold"
				style={{ left: `${(Math.min(pos, n) / n) * 100}%` }}
			/>
		</div>
	);
}
