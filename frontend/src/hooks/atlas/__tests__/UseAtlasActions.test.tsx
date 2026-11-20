import { waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "@/api/Http";
import { useAtlasActions } from "@/hooks/atlas/UseAtlasActions";
import { useAppStore } from "@/store/AppStore";
import { renderWithApp } from "@/test/RenderWithApp";

let actions: ReturnType<typeof useAtlasActions>;
function Probe() {
	actions = useAtlasActions();
	return null;
}

const shot = (name: string) => new File(["x"], name, { type: "image/png" });

describe("useAtlasActions: dropped screenshots", () => {
	it("adds the ones sent and names the ones that could not be", async () => {
		// (GPT audit: one failing upload dropped them all, the ones already sent left unused)
		let n = 0;
		const { calls } = renderWithApp(<Probe />, {
			"POST /api/upload": (b: unknown) =>
				(b as { name: string }).name === "bad.png" ? new ApiError("too large", 413) : { path: `C:/up/${++n}.png` },
			"POST /api/screenshots": { queued: 2 },
		});
		await actions.dropFiles([shot("a.png"), shot("bad.png"), shot("c.png")]);
		await waitFor(() =>
			expect(calls.find((c) => c.path === "/api/screenshots")?.body).toMatchObject({
				paths: ["C:/up/1.png", "C:/up/2.png"],
			}),
		);
		expect(useAppStore.getState().error).toContain("1 of 3 screenshot(s) could not be sent");
		expect(useAppStore.getState().error).toContain("bad.png (too large)");
	});
});
