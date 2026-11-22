import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import { useAppStore } from "@/store/AppStore";

/**
 * The timelapse's tab, at the bottom right of the map as in the old window (user: Replay looked out of place in the top
 * bar), shaped as the top bar's stash tabs, its curves landing on the map's bottom edge (no bar of its own: user): lit
 * while the timelapse is open under the map, the game's reveal triangle on it pointing the way it goes.
 */
export function TimelapseTab() {
	const app = useAppClient();
	const state = useAppState().data;
	const replay = useAppStore((s) => s.replay);
	const setReplay = useAppStore((s) => s.setReplay);
	const showError = useAppStore((s) => s.showError);
	if (!state?.atlas?.shots) return null;
	const open = !!replay;

	const toggle = async () => {
		if (useAppStore.getState().replay) {
			setReplay(null);
			await app.closeReplay().catch(showError);
			return;
		}
		try {
			const plan = await app.openReplay();
			setReplay({ plan, pos: plan.n_steps, playing: false, recording: false });
		} catch (e) {
			showError(e);
		}
	};

	return (
		// (placed by its own box: the tab group's styles keep it relative)
		<div className="absolute right-4 bottom-0 z-10 flex">
			<div className="poe-tools">
				<button
					type="button"
					className="poe-tab"
					data-on={open || undefined}
					aria-pressed={open}
					title={open ? "Close the timelapse" : "Timelapse: the atlas being made, as a replay"}
					onClick={() => void toggle()}
				>
					<span className={open ? "poe-reveal-up rotate-180" : "poe-reveal-up"} aria-hidden="true" />
					Timelapse
				</button>
			</div>
		</div>
	);
}
