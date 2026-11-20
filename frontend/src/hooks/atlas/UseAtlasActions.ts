import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import type { AppState } from "@/domain/app/AppState";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import { useAppStore } from "@/store/AppStore";
import { baseName, plural } from "@/utils/Format";

/** The File and Atlas menus' flows: open / new / folder / add / place by hand / close, with their questions. */
export function useAtlasActions() {
	const app = useAppClient();
	const queryClient = useQueryClient();
	const state = useAppState().data;
	const atlasFolder = state?.atlas ? state.atlas.path.replace(/[\\/][^\\/]*$/, "") : "";

	const fail = useCallback((e: unknown) => useAppStore.getState().showError(e), []);

	// what belonged to the atlas before is cleared when the state says another one is open (useAppState: also when
	// another tab opened it); here only the state is asked for at once
	const afterOpen = useCallback(
		() => void queryClient.invalidateQueries({ queryKey: AppQueryKeys.state }),
		[queryClient],
	);

	const openAtlas = useCallback(
		(path: string) => app.openAtlas(path).then(afterOpen).catch(fail),
		[app, afterOpen, fail],
	);

	const askOpenAtlas = useCallback(
		() =>
			useAppStore.getState().pickFiles({
				title: "Open an atlas (its .json file)",
				folders: false,
				start: atlasFolder,
				onPick: ([p]) => p && void openAtlas(p),
			}),
		[atlasFolder, openAtlas],
	);

	const askNewAtlas = useCallback(
		() =>
			useAppStore.getState().pickFiles({
				title: "New atlas: pick its folder and name",
				folders: true,
				save: "atlas.json",
				start: atlasFolder,
				onPick: ([p]) => p && void app.newAtlas(p).then(afterOpen).catch(fail),
			}),
		[app, atlasFolder, afterOpen, fail],
	);

	const addScreenshots = useCallback(
		(paths: string[]) =>
			paths.length
				? app
						.addScreenshots(paths)
						.then(() => queryClient.invalidateQueries({ queryKey: AppQueryKeys.state }))
						.catch(fail)
				: undefined,
		[app, queryClient, fail],
	);

	const openFolder = useCallback(
		async (folder: string) => {
			try {
				const r = await app.openFolder(folder);
				if ("create" in r) {
					useAppStore.getState().askConfirm({
						title: "New atlas",
						text: `No atlas in this folder yet. Build one from its ${plural(r.create, "screenshot")}? It is saved as atlas.json in the folder.`,
						yes: "Build it",
						onYes: () => void app.createFromFolder(folder).then(afterOpen).catch(fail),
					});
					return;
				}
				// asked once the page has the opened atlas's state (its atlas reset cleared a question asked before it)
				// and only while that atlas is still the open one (another opened meanwhile: CodeRabbit)
				await queryClient.refetchQueries({ queryKey: AppQueryKeys.state });
				const now = queryClient.getQueryData<AppState>(AppQueryKeys.state)?.atlas?.path;
				if (r.new.length && now === r.opened)
					useAppStore.getState().askConfirm({
						title: "Atlas folder",
						text: `${plural(r.new.length, "screenshot")} in this folder are not in the atlas yet. Add them now?`,
						yes: "Add them",
						onYes: () => void addScreenshots(r.new),
					});
			} catch (e) {
				fail(e);
			}
		},
		[app, queryClient, afterOpen, addScreenshots, fail],
	);

	const askOpenFolder = useCallback(
		() =>
			useAppStore.getState().pickFiles({
				title: "Atlas folder (its screenshots, and atlas.json if it has one)",
				folders: true,
				start: atlasFolder,
				onPick: ([p]) => p && void openFolder(p),
			}),
		[atlasFolder, openFolder],
	);

	const askAddScreenshots = useCallback(
		() =>
			useAppStore.getState().pickFiles({
				title: "Add atlas screenshots",
				folders: false,
				multiple: true,
				start: atlasFolder,
				onPick: (paths) => void addScreenshots(paths),
			}),
		[atlasFolder, addScreenshots],
	);

	/** Show a screenshot see-through in the middle of the map, to drag roughly where it belongs. */
	const startGhost = useCallback(
		async (path: string) => {
			try {
				const ghost = await app.ghost(path);
				const s = useAppStore.getState();
				const cam = s.camera;
				s.setMode({ kind: "ghost", ghost, centre: cam ? [cam.x, cam.y] : [0, 0] });
				s.showError(null);
				s.setTab("auto");
				queryClient.setQueryData(AppQueryKeys.state, (old: typeof state) =>
					old
						? {
								...old,
								status: `${baseName(path)}: drag it roughly where it belongs, then press Enter or double-click (Esc cancels)`,
							}
						: old,
				);
			} catch (e) {
				fail(e);
			}
		},
		[app, queryClient, fail],
	);

	const askPlaceByHand = useCallback(
		() =>
			useAppStore.getState().pickFiles({
				title: "Screenshot to place by hand",
				folders: false,
				start: state?.watch.folder || atlasFolder,
				onPick: ([p]) => p && void startGhost(p),
			}),
		[state?.watch.folder, atlasFolder, startGhost],
	);

	/** Files dropped on the page: copied into the atlas's folder; one is placed by hand, several added. */
	const dropFiles = useCallback(
		async (files: File[]) => {
			const shots = files.filter((f) => /\.(png|jpe?g|webp|bmp)$/i.test(f.name));
			if (!shots.length) return fail("Drop screenshot image files (.png, .jpg).");
			// each file on its own: the ones sent are placed, the others named (one failing upload dropped them all,
			// the ones already sent left unused: GPT audit)
			const paths: string[] = [];
			const failed: string[] = [];
			for (const f of shots) {
				try {
					paths.push((await app.upload(f)).path);
				} catch (e) {
					failed.push(`${f.name} (${e instanceof Error ? e.message : String(e)})`);
				}
			}
			if (paths.length === 1 && shots.length === 1) return startGhost(paths[0]);
			// added here, not through addScreenshots (which shows its own error): one message says both what wasn't
			// sent and whether the rest went in (the add's error was hidden by the upload one: self review)
			let addError = "";
			if (paths.length)
				try {
					await app.addScreenshots(paths);
					void queryClient.invalidateQueries({ queryKey: AppQueryKeys.state });
				} catch (e) {
					addError = e instanceof Error ? e.message : String(e);
				}
			if (!failed.length) {
				if (addError) fail(addError);
				return;
			}
			const rest = !paths.length
				? ""
				: addError
					? ` The other ${paths.length} could not be added: ${addError}`
					: ` The other ${paths.length} are being added.`;
			fail(`${failed.length} of ${shots.length} screenshot(s) could not be sent: ${failed.join(", ")}.${rest}`);
		},
		[app, queryClient, startGhost, fail],
	);

	const closeAtlas = useCallback(() => app.closeAtlas().then(afterOpen).catch(fail), [app, afterOpen, fail]);

	return useMemo(
		() => ({
			openAtlas,
			askOpenAtlas,
			askNewAtlas,
			openFolder,
			askOpenFolder,
			addScreenshots,
			askAddScreenshots,
			startGhost,
			askPlaceByHand,
			dropFiles,
			closeAtlas,
		}),
		[
			openAtlas,
			askOpenAtlas,
			askNewAtlas,
			openFolder,
			askOpenFolder,
			addScreenshots,
			askAddScreenshots,
			startGhost,
			askPlaceByHand,
			dropFiles,
			closeAtlas,
		],
	);
}
