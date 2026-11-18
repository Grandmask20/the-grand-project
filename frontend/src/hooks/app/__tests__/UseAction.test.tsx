import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/Http";
import { useAction } from "@/hooks/app/UseAction";
import { useAppStore } from "@/store/AppStore";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

function Probe({ report, onSuccess }: { report?: boolean; onSuccess?: (r: unknown, v: string) => void }) {
	const save = useAction((app, name: string) => app.renameAtlas("/a/atlas.json", name), {
		invalidate: [["atlases"]],
		onSuccess,
		report,
	});
	return (
		<button type="button" onClick={() => save.mutate("Run 2")}>
			go
		</button>
	);
}

describe("useAction", () => {
	afterEach(resetStore);

	it("calls the app, then fetches the queries it changed", async () => {
		const onSuccess = vi.fn();
		const { user, calls, queryClient } = renderWithApp(<Probe onSuccess={onSuccess} />, {
			"POST /api/atlases/rename": { ok: true },
		});
		const spy = vi.spyOn(queryClient, "invalidateQueries");
		await user.click(screen.getByRole("button", { name: "go" }));
		await waitFor(() => expect(onSuccess).toHaveBeenCalledWith({ ok: true }, "Run 2"));
		expect(calls.find((c) => c.path === "/api/atlases/rename")?.body).toEqual({ json: "/a/atlas.json", name: "Run 2" });
		expect(spy).toHaveBeenCalledWith({ queryKey: ["atlases"] });
	});

	it("shows a failure in the error box, unless told not to", async () => {
		const routes = { "POST /api/atlases/rename": new ApiError("that name is taken", 400) };
		const first = renderWithApp(<Probe />, routes);
		await first.user.click(screen.getByRole("button", { name: "go" }));
		await waitFor(() => expect(useAppStore.getState().error).toBe("that name is taken"));
		first.unmount();
		resetStore();
		const quiet = renderWithApp(<Probe report={false} />, routes);
		await quiet.user.click(screen.getByRole("button", { name: "go" }));
		await new Promise((r) => setTimeout(r, 20));
		expect(useAppStore.getState().error).toBeNull();
	});
});
