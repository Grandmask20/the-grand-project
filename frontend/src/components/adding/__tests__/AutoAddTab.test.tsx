import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AutoAddTab } from "@/components/adding/AutoAddTab";
import { useAppStore } from "@/store/AppStore";
import { renderWithApp } from "@/test/RenderWithApp";

describe("AutoAddTab", () => {
	it("shows the watched folder, the recent additions and what is waiting", () => {
		renderWithApp(<AutoAddTab />);
		expect(screen.getByText("watching this atlas's folder: /atlases/default")).toBeInTheDocument();
		expect(screen.getByText(/NEWEST/)).toHaveTextContent("shot_3.png");
		expect(screen.getByText(/waiting, tried 2x/)).toBeInTheDocument();
	});

	it("turns auto-add on", async () => {
		const { user, calls } = renderWithApp(<AutoAddTab />, {
			"POST /api/watch": { on: true, folder: "/atlases/default", picked: false },
		});
		await user.click(screen.getByRole("switch", { name: "Add new screenshots automatically" }));
		await waitFor(() => expect(calls.find((c) => c.path === "/api/watch")?.body).toEqual({ on: true }));
	});

	it("asks before undoing the last add", async () => {
		const { user } = renderWithApp(<AutoAddTab />);
		await user.click(screen.getByRole("button", { name: "Undo last add" }));
		expect(useAppStore.getState().confirm?.text).toContain("shot_3.png");
	});

	it("takes a waiting screenshot out to place it by hand", async () => {
		const { user, calls } = renderWithApp(<AutoAddTab />, {
			"POST /api/waiting/take": { path: "/atlases/default/lost.png" },
			"POST /api/ghost": {
				picture: 1,
				box: [-480, -270, 480, 270],
				name: "lost.png",
				path: "/atlases/default/lost.png",
			},
		});
		await user.click(screen.getByRole("button", { name: /lost.png/ }));
		await user.click(screen.getByRole("button", { name: "Place by hand" }));
		await waitFor(() => expect(useAppStore.getState().mode.kind).toBe("ghost"));
		expect(calls.find((c) => c.path === "/api/waiting/take")?.body).toEqual({ index: 0 });
	});
});
