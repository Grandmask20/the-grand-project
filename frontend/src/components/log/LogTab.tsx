import { useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useAppState } from "@/hooks/app/UseAppState";
import { frameLog } from "@/logic/FrameLog";
import { useAppStore } from "@/store/AppStore";
import { download } from "@/utils/Download";

/** The app's log, newest at the bottom; the frame log (how long the map takes to draw) can be saved as CSV. */
export function LogTab() {
	const log = useAppState().data?.log ?? [];
	const end = useRef<HTMLDivElement>(null);
	const recording = useAppStore((s) => s.frameLog);
	const setFrameLog = useAppStore((s) => s.setFrameLog);

	// biome-ignore lint/correctness/useExhaustiveDependencies: scrolls down with every new line
	useEffect(() => {
		end.current?.scrollIntoView({ block: "end" });
	}, [log.length]);

	return (
		<div className="flex h-full flex-col gap-2">
			<div className="flex items-center gap-3">
				<Button size="xs" variant="outline" onClick={() => download(`${log.join("\n")}\n`, "grand-project-log.txt")}>
					Save log
				</Button>
				<Label className="font-normal">
					<Switch checked={recording} onCheckedChange={setFrameLog} aria-label="Frame log" />
					Frame log
				</Label>
				{recording && (
					<Button size="xs" variant="outline" onClick={() => download(frameLog.csv(), "frame-log.csv", "text/csv")}>
						Save frame log ({frameLog.size})
					</Button>
				)}
			</div>
			<div className="flex-1 overflow-y-auto rounded border bg-card p-2 font-mono text-xs leading-5 whitespace-pre-wrap">
				{log.map((line, k) => (
					// biome-ignore lint/suspicious/noArrayIndexKey: log lines repeat
					<div key={k}>{line}</div>
				))}
				<div ref={end} />
			</div>
		</div>
	);
}
