import { useEffect, useRef, useState } from "react";

/** What the app is doing, with moving dots and the seconds it has taken (top right of the map). */
export function ProgressBox({ text }: { text: string | null }) {
	const started = useRef<number | null>(null);
	const [, tick] = useState(0);

	if (text && started.current === null) started.current = Date.now();
	if (!text) started.current = null;

	useEffect(() => {
		if (!text) return;
		const t = setInterval(() => tick((n) => n + 1), 500);
		return () => clearInterval(t);
	}, [text]);

	if (!text || started.current === null) return null;
	const secs = Math.round((Date.now() - started.current) / 1000);
	const dots = ".".repeat(1 + (Math.floor(Date.now() / 500) % 3));
	return (
		<div
			role="status"
			className="absolute top-3 right-14 z-30 poe-panel poe-panel-sm px-3 py-1.5 font-mono text-xs text-gold shadow"
		>
			{text.replace(/[.…]+$/, "")}
			{dots} <span className="text-muted-foreground">{secs}s</span>
		</div>
	);
}
