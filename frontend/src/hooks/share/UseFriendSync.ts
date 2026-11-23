import { useEffect, useRef } from "react";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import { useAppStore } from "@/store/AppStore";
import { useShareStore } from "@/store/ShareStore";

/**
 * A friend's atlas, as it comes over a watch link, handed to this app (live sharing): kept there (POST
 * /api/friends) and opened as any atlas, read-only, with their view (user: "their map as they see it"); each new one
 * kept again (the one open is read again in place), where they are (I'm here) kept with it. While their atlas is
 * open, their route is the one shown.
 */
export function useFriendSync(): void {
	const app = useAppClient();
	const links = useShareStore((s) => s.links);
	const kept = useShareStore((s) => s.kept);
	const open = useAppState().data?.atlas?.path ?? "";
	const setRoute = useAppStore((s) => s.setRoute);
	const savedFile = useRef(new Map<number, string>());
	const savedPos = useRef(new Map<number, string>());
	const shownRoute = useRef(new Map<number, string>());

	useEffect(() => {
		const fail = (e: unknown) => useAppStore.getState().showError(e);
		for (const l of links) {
			if (l.role !== "watch") continue;
			const name = l.friend || "Friend";
			const pos = JSON.stringify(l.player);
			if (l.file && savedFile.current.get(l.id) !== l.file) {
				savedFile.current.set(l.id, l.file);
				savedPos.current.set(l.id, pos);
				app
					.saveFriend(name, l.file, l.player)
					.then((r) => kept(l.id, r.json))
					.catch(fail);
			} else if (l.atlasPath && savedPos.current.get(l.id) !== pos) {
				savedPos.current.set(l.id, pos);
				app.setFriendPlayer(name, l.player).catch(fail);
			}
			// their route, while their atlas is open (opened since: shown then)
			const theirs = !!l.atlasPath && l.atlasPath === open;
			const route = `${theirs}|${JSON.stringify(l.route)}`;
			if (theirs && shownRoute.current.get(l.id) !== route)
				setRoute(l.route?.length ? { path: l.route, message: `${name}'s route` } : null);
			shownRoute.current.set(l.id, route);
		}
	}, [links, open, app, kept, setRoute]);
}
