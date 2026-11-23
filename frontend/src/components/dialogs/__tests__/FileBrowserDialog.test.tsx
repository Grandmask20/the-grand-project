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

	it("a folder typed before the first listing comes is kept, and Enter opens it (CI: the listing wrote over it)", async () => {
		const shots = { ...home, path: "/home/me/shots", parent: "/home/me", entries: [home.entries[1]] };
		let release: () => void = () => {};
		const late = new Promise<void>((r) => {
			release = r;
		});
		const { user, calls } = renderWithApp(<FileBrowserDialog />, {
			"GET /api/fs": async (_b: unknown, p?: Record<string, unknown>) => {
				if (p?.path === "/home/me/shots") return shots;
				await late; // the start folder answers only after you've typed
				return home;
			},
		});
		act(() =>
			useAppStore
				.getState()
				.pickFiles({ title: "Add atlas screenshots", folders: false, multiple: true, onPick: vi.fn() }),
		);
		const box = screen.getByRole("textbox", { name: "Folder" });
		await user.type(box, "/home/me/shots");
		await act(async () => release());
		expect(box).toHaveValue("/home/me/shots");
		await user.type(box, "{Enter}");
		await waitFor(() => expect(calls.some((c) => c.params?.path === "/home/me/shots")).toBe(true));
		expect(await screen.findByRole("button", { name: /a.png/ })).toBeInTheDocument();
	});

	it("names a new atlas in the folder it is in", async () => {
		const onPick = vi.fn();
		const { user } = renderWithApp(<FileBrowserDialog />, { "GET /api/fs": home });
		act(() => useAppStore.getState().pickFiles({ title: "New atlas", folders: true, save: "atlas.json", onPick }));
		await screen.findAllByRole("button", { name: /shots/ }); // in the list and unfolded in the folder tree
		await user.click(screen.getByRole("button", { name: "Create" }));
		expect(onPick).toHaveBeenCalledWith(["/home/me/atlas.json"]);
	});
});
