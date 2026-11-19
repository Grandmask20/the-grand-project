import { act, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MapNotes } from "@/components/map/MapNotes";
import { useAppStore } from "@/store/AppStore";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

describe("MapNotes", () => {
	afterEach(resetStore);

	it("a map mode's note has End (user: only Esc ended one)", async () => {
		const { user } = renderWithApp(<MapNotes />);
		act(() => useAppStore.getState().setMode({ kind: "route-edit", id: 5 }));
		expect(screen.getByText(/Adjust route: click a map/)).toBeInTheDocument();
		await user.click(screen.getByRole("button", { name: "End" }));
		expect(useAppStore.getState().mode).toEqual({ kind: "normal" });
	});

	it("says the other view's settings don't show, and puts the error under the notes, not over them", () => {
		const { container } = renderWithApp(<MapNotes />);
		act(() => {
			useAppStore.getState().setMode({ kind: "route-edit", id: 5 });
			useAppStore.getState().hold("view:3d");
			useAppStore.getState().showError("A route needs two maps: delete it instead.", true);
		});
		expect(screen.getByRole("status")).toHaveTextContent("3D view's settings");
		const column = container.firstElementChild as HTMLElement;
		const texts = [...column.children].map((c) => c.textContent ?? "");
		expect(texts[0]).toMatch(/Adjust route/);
		expect(texts[texts.length - 1]).toMatch(/A route needs two maps/);
	});
});
