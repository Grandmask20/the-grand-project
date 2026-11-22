import { ChevronLeftIcon, ChevronRightIcon, PauseIcon, PlayIcon, XIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useBookmarks } from "@/hooks/bookmarks/UseBookmarks";
import { useAppStore } from "@/store/AppStore";

/** On play, the next bookmark after this many ms. */
export const TOUR_MS = 3500;

/**
 * A bookmark group's tour (MapLibre's "Jump to a series of locations"): the camera flies to each bookmark of the group
 * in turn and selects it, with Back and Next (or ← →), Play to go on by itself, and its x (or Esc) to end it. Started
 * from a group's play button in Bookmarks; a saved route has no spot of its own, so it is left out.
 */
export function BookmarkTour() {
	const app = useAppClient();
	const tour = useAppStore((s) => s.tour);
	const setTour = useAppStore((s) => s.setTour);
	const flyTo = useAppStore((s) => s.flyTo);
	const selectLoaded = useAppStore((s) => s.selectLoaded);
	const showError = useAppStore((s) => s.showError);
	const bookmarks = useBookmarks(!!tour);
	const [playing, setPlaying] = useState(false);

	const stops = useMemo(
		() => bookmarks.data?.groups.find((g) => g.name === tour?.group)?.items.filter((b) => !b.route) ?? [],
		[bookmarks.data, tour?.group],
	);
	const n = stops.length;
	const at = tour ? Math.min(tour.at, Math.max(0, n - 1)) : 0;
	const stop = n ? stops[at] : null;
	const go = (by: number) => tour && n && setTour({ group: tour.group, at: (at + by + n) % n });

	// each stop: the camera there, the bookmark selected (once a stop: not again when the list refreshes)
	const shown = useRef<number | null>(null);
	useEffect(() => {
		if (!stop) {
			shown.current = null;
			return;
		}
		if (shown.current === stop.id) return;
		shown.current = stop.id;
		flyTo(stop.x, stop.y, 1);
		selectLoaded(app.getInfo("bookmark", stop.id)).catch(showError);
	}, [stop, flyTo, selectLoaded, app, showError]);

	// the group gone, or emptied: the tour ends
	useEffect(() => {
		if (tour && bookmarks.data && !n) setTour(null);
	}, [tour, bookmarks.data, n, setTour]);
	useEffect(() => {
		if (!tour) setPlaying(false);
	}, [tour]);

	// playing: on to the next by itself
	useEffect(() => {
		if (!playing || !tour || n < 2) return;
		const t = setTimeout(() => setTour({ group: tour.group, at: (at + 1) % n }), TOUR_MS);
		return () => clearTimeout(t);
	}, [playing, tour, at, n, setTour]);

	// ← → Esc while it runs (not while typing)
	useEffect(() => {
		if (!tour) return;
		const key = (e: KeyboardEvent) => {
			const t = e.target as HTMLElement | null;
			if (t?.closest?.("input, textarea, select, [contenteditable='true']")) return;
			if (e.key === "ArrowRight") go(1);
			else if (e.key === "ArrowLeft") go(-1);
			else if (e.key === "Escape") setTour(null);
			else return;
			e.preventDefault();
		};
		window.addEventListener("keydown", key);
		return () => window.removeEventListener("keydown", key);
	});

	if (!tour || !stop) return null;
	const btn = "rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground";
	return (
		<div
			role="toolbar"
			aria-label="Bookmark tour"
			className="absolute bottom-10 left-1/2 z-30 flex -translate-x-1/2 items-center gap-1 rounded-md border bg-card/95 px-2 py-1 text-sm shadow"
		>
			<button type="button" aria-label="Back" title="Back (←)" onClick={() => go(-1)} className={btn}>
				<ChevronLeftIcon className="size-4" />
			</button>
			<button
				type="button"
				aria-label={playing ? "Pause" : "Play"}
				title={playing ? "Pause" : "Go on by itself"}
				onClick={() => setPlaying(!playing)}
				className={btn}
			>
				{playing ? <PauseIcon className="size-4" /> : <PlayIcon className="size-4" />}
			</button>
			<span className="min-w-0 max-w-64 truncate px-1">
				<span className="text-muted-foreground">
					{tour.group} {at + 1}/{n}
				</span>{" "}
				{stop.name}
			</span>
			<button type="button" aria-label="Next" title="Next (→)" onClick={() => go(1)} className={btn}>
				<ChevronRightIcon className="size-4" />
			</button>
			<button
				type="button"
				aria-label="End the tour"
				title="End the tour (Esc)"
				onClick={() => setTour(null)}
				className={btn}
			>
				<XIcon className="size-4" />
			</button>
		</div>
	);
}
