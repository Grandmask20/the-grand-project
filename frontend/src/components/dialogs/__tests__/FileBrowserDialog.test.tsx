import { act, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FileBrowserDialog } from "@/components/dialogs/FileBrowserDialog";
import { useAppStore } from "@/store/AppStore";
import { renderWithApp } from "@/test/RenderWithApp";

const home = {
	path: "/home/me",
	parent: "/home",
	truncated: false,
	entries: [
		{ name: "shots", path: "/home/me/shots", dir: true, size: 0 },
		{ name: "a.png", path: "/home/me/a.png", dir: false, size: 2048 },
		{ name: "b.png", path: "/home/me/b.png", dir: false, size: 4096 },
	],
};

describe("FileBrowserDialog", () => {
	it("picks several files", async () => {
		const onPick = vi.fn();
		const { user } = renderWithApp(<FileBrowserDialog />, { "GET /api/fs": home });
		act(() =>
			useAppStore.getState().pickFiles({ title: "Add atlas screenshots", folders: false, multiple: true, onPick }),
		);
		await user.click(await screen.findByRole("button", { name: /a.png/ }));
		await user.click(screen.getByRole("button", { name: /b.png/ }));
		await user.click(screen.getByRole("button", { name: "Open" }));
		expect(onPick).toHaveBeenCalledWith(["/home/me/a.png", "/home/me/b.png"]);
		await waitFor(() => expect(useAppStore.getState().filePick).toBeNull());
	});

	it("names a new atlas in the folder it is in", async () => {
		const onPick = vi.fn();
		const { user } = renderWithApp(<FileBrowserDialog />, { "GET /api/fs": home });
		act(() => useAppStore.getState().pickFiles({ title: "New atlas", folders: true, save: "atlas.json", onPick }));
		await screen.findByRole("button", { name: /shots/ });
		await user.click(screen.getByRole("button", { name: "Create" }));
		expect(onPick).toHaveBeenCalledWith(["/home/me/atlas.json"]);
	});
});
