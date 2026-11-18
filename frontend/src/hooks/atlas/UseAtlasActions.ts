import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import { useAppStore } from "@/store/AppStore";
import { baseName, plural } from "@/utils/Format";

/** The File and Atlas menus' flows: open / new / folder / add / place by hand / close, with their questions. */
export function useAtlasActions() {
	const app = useAppClient();
	const queryClient = useQueryClient();
	const state = useAppState().data;
	const store = useAppStore;
	const atlasFolder = state?.atlas ? state.atlas.path.replace(/[\\/][^\\/]*$/, "") : "";

	const fail = useCallback((e: unknown) => store.getState().showError(e), [store]);
	const refreshAll = useCallback(() => queryClient.invalidateQueries(), [queryClient]);

	const afterOpen = useCallback(() => {
		const s = store.getState();
		s.select(null);
		s.setResults([], "");
		s.setRoute(null);
		s.setCamera(null);
		s.setGoto(null);
		void refreshAll();
	}, [store, refreshAll]);

	const openAtlas = useCallback(
		(path: string) =>
			app
				.openAtlas(path)
				.then(afterOpen)
				.catch(fail),
		[app, afterOpen, fail],
	);

	const askOpenAtlas = useCallback(
		() =>
			store.getState().pickFiles({
				title: "Open an atlas (its .json file)",
				folders: false,
				start: atlasFolder,
				onPick: ([p]) => p && void openAtlas(p),
			}),
		[store, atlasFolder, openAtlas],
	);

	const askNewAtlas = useCallback(
		() =>
			store.getState().pickFiles({
				title: "New atlas: pick its folder and name",
				folders: true,
				save: "atlas.json",
				start: atlasFolder,
				onPick: ([p]) =>
					p &&
					void app
						.newAtlas(p)
						.then(afterOpen)
						.catch(fail),
			}),
		[store, app, atlasFolder, afterOpen, fail],
	);

	const addScreenshots = useCallback(
		(paths: string[]) =>
			paths.length ? app.addScreenshots(paths).then(() => queryClient.invalidateQueries({ queryKey: AppQueryKeys.state })).catch(fail) : undefined,
		[app, queryClient, fail],
	);

	const openFolder = useCallback(
		async (folder: string) => {
			try {
				const r = await app.openFolder(folder);
				if ("create" in r) {
					store.getState().askConfirm({
						title: "New atlas",
						text: `No atlas in this folder yet. Build one from its ${plural(r.create, "screenshot")}? It is saved as atlas.json in the folder.`,
						yes: "Build it",
						onYes: () =>
							void app
								.createFromFolder(folder)
								.then(afterOpen)
								.catch(fail),
					});
					return;
				}
				afterOpen();
				if (r.new.length)
					store.getState().askConfirm({
						title: "Atlas folder",
						text: `${plural(r.new.length, "screenshot")} in this folder are not in the atlas yet. Add them now?`,
						yes: "Add them",
						onYes: () => void addScreenshots(r.new),
					});
			} catch (e) {
				fail(e);
			}
		},
		[app, store, afterOpen, addScreenshots, fail],
	);

	const askOpenFolder = useCallback(
		() =>
			store.getState().pickFiles({
				title: "Atlas folder (its screenshots, and atlas.json if it has one)",
				folders: true,
				start: atlasFolder,
				onPick: ([p]) => p && void openFolder(p),
			}),
		[store, atlasFolder, openFolder],
	);

	const askAddScreenshots = useCallback(
		() =>
			store.getState().pickFiles({
				title: "Add atlas screenshots",
				folders: false,
				multiple: true,
				start: atlasFolder,
				onPick: (paths) => void addScreenshots(paths),
			}),
		[store, atlasFolder, addScreenshots],
	);

	/** Show a screenshot see-through in the middle of the map, to drag roughly where it belongs. */
	const startGhost = useCallback(
		async (path: string) => {
			try {
				const ghost = await app.ghost(path);
				const s = store.getState();
				const cam = s.camera;
				s.setMode({ kind: "ghost", ghost, centre: cam ? [cam.x, cam.y] : [0, 0] });
				s.showError(null);
				s.setTab("auto");
				queryClient.setQueryData(AppQueryKeys.state, (old: typeof state) =>
					old ? { ...old, status: `${baseName(path)}: drag it roughly where it belongs, then press Enter or double-click (Esc cancels)` } : old,
				);
			} catch (e) {
				fail(e);
			}
		},
		[app, store, queryClient, fail],
	);

	const askPlaceByHand = useCallback(
		() =>
			store.getState().pickFiles({
				title: "Screenshot to place by hand",
				folders: false,
				start: state?.watch.folder || atlasFolder,
				onPick: ([p]) => p && void startGhost(p),
			}),
		[store, state?.watch.folder, atlasFolder, startGhost],
	);

	/** Files dropped on the page: copied into the atlas's folder; one is placed by hand, several added. */
	const dropFiles = useCallback(
		async (files: File[]) => {
			const shots = files.filter((f) => /\.(png|jpe?g|webp|bmp)$/i.test(f.name));
			if (!shots.length) return fail("Drop screenshot image files (.png, .jpg).");
			try {
				const paths = [];
				for (const f of shots) paths.push((await app.upload(f)).path);
				if (paths.length === 1) await startGhost(paths[0]);
				else await addScreenshots(paths);
			} catch (e) {
				fail(e);
			}
		},
		[app, startGhost, addScreenshots, fail],
	);

	const closeAtlas = useCallback(
		() =>
			app
				.closeAtlas()
				.then(afterOpen)
				.catch(fail),
		[app, afterOpen, fail],
	);

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
