import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FriendAtlas } from "@/components/share/FriendAtlas";
import type { SharedPlayer } from "@/domain/share/SharedAtlas";
import { resetShare, useShareStore } from "@/store/ShareStore";
import { type FakeMap, fakeMap } from "@/test/FakeMap";
import { setMap } from "@/test/ReactMapGlMock";
import { renderWithApp } from "@/test/RenderWithApp";
import { sharedAtlas } from "@/test/ShareAtlas";

// react-map-gl's Map: draws its children on the fake map and says it loaded
vi.mock("react-map-gl/maplibre", async () => {
	const mock = await import("@/test/ReactMapGlMock");
	const { useEffect } = await import("react");
	const { current } = await import("@/test/FakeMapRef");
	return {
		...mock,
		Map: ({ children, onLoad }: { children: React.ReactNode; onLoad?: (e: { target: unknown }) => void }) => {
			useEffect(() => onLoad?.({ target: current.map?.map }), [onLoad]);
			return children;
		},
	};
});

import { current } from "@/test/FakeMapRef";

let fm: FakeMap;
const watching = (state: "live" | "closed", player: SharedPlayer | null = null) =>
	useShareStore.setState({
		viewing: 7,
		links: [
			{ id: 7, role: "watch", state, code: "", friend: "Nyx", atlas: sharedAtlas, player, updated: 0, error: "" },
		],
	});

describe("FriendAtlas", () => {
	beforeEach(() => {
		fm = fakeMap({ style: false });
		setMap(fm);
		current.map = fm;
	});
	afterEach(() => {
		resetShare();
		setMap(null);
	});

	it("nothing open: nothing shown", () => {
		renderWithApp(<FriendAtlas />);
		expect(screen.queryByRole("region", { name: "Friend's atlas" })).toBeNull();
	});

	it("their atlas: named, live, their maps, paths, icons, landmarks and them drawn, the icons' pictures loaded", async () => {
		watching("live", { x: 100, y: 0, node: 2 });
		renderWithApp(<FriendAtlas />);
		expect(screen.getByText("Nyx's atlas")).toBeInTheDocument();
		expect(screen.getByText("nyx atlas")).toBeInTheDocument();
		expect(screen.getByText("3 maps · 1 landmarks")).toBeInTheDocument();
		expect(screen.getByText("● live")).toBeInTheDocument();
		const data = (id: string) => (fm.sources.get(id)?.data as { features: unknown[] } | undefined)?.features.length;
		expect([
			data("friend-maps"),
			data("friend-paths"),
			data("friend-icons"),
			data("friend-landmarks"),
			data("friend-here"),
		]).toEqual([3, 2, 3, 1, 1]);
		await waitFor(() => expect([...fm.images.keys()].sort()).toEqual(["Abyss", "Breach", "Ritual"]));
	});

	it("their link closed: what they sent last, said so; Close puts your map back", async () => {
		watching("closed");
		const { user } = renderWithApp(<FriendAtlas />);
		expect(screen.getByText("link closed: what they sent last")).toBeInTheDocument();
		await user.click(screen.getByRole("button", { name: "Close their atlas" }));
		expect(useShareStore.getState().viewing).toBeNull();
		expect(screen.queryByRole("region", { name: "Friend's atlas" })).toBeNull();
	});
});
