import { XIcon } from "lucide-react";
import { useEffect } from "react";
import { useAppStore } from "@/store/AppStore";

/** The last error, over the map until closed (or 12 s); a brief one also closes on the next click anywhere. */
export function ErrorBanner() {
	const error = useAppStore((s) => s.error);
	const brief = useAppStore((s) => s.errorBrief);
	const showError = useAppStore((s) => s.showError);

	useEffect(() => {
		if (!error) return;
		const t = setTimeout(() => showError(null), 12_000);
		return () => clearTimeout(t);
	}, [error, showError]);

	// a note about the last click (no maps inside the lasso) is over once anything else is clicked: a new lasso, a
	// button, the side panel (user: it stayed up for its 12 s, and nothing says you draw another lasso)
	useEffect(() => {
		if (!error || !brief) return;
		const shown = error;
		const close = () => {
			if (useAppStore.getState().error === shown) showError(null);
		};
		window.addEventListener("pointerdown", close, { capture: true, once: true });
		return () => window.removeEventListener("pointerdown", close, { capture: true });
	}, [error, brief, showError]);

	if (!error) return null;
	return (
		<div
			role="alert"
			className="absolute top-3 left-1/2 z-40 flex max-w-[70%] -translate-x-1/2 items-start gap-3 rounded-md border border-destructive/60 bg-card px-3 py-2 shadow-lg"
		>
			<span className="whitespace-pre-wrap">{error}</span>
			<button type="button" aria-label="Close" className="opacity-70 hover:opacity-100" onClick={() => showError(null)}>
				<XIcon className="size-4" />
			</button>
		</div>
	);
}
