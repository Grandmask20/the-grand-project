import { waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError, setAtlasGen } from "@/api/Http";
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
		expect(useAppStore.getState().error).toContain("The other 2 are being added.");
	});

	it("says when the ones sent could not be added either", async () => {
		// (self review: the add's own error was hidden by the upload one)
		renderWithApp(<Probe />, {
			"POST /api/upload": (b: unknown) =>
				(b as { name: string }).name === "bad.png" ? new ApiError("too large", 413) : { path: "C:/up/1.png" },
			"POST /api/screenshots": new ApiError("no atlas open", 409),
		});
		await actions.dropFiles([shot("a.png"), shot("bad.png")]);
		expect(useAppStore.getState().error).toContain("The other 1 could not be added: no atlas open");
	});

	it("stops when another atlas opens during the drop: nothing more is sent or added", async () => {
		// (CodeRabbit: later files went to the new atlas, and the paths were added there)
		setAtlasGen(1);
		let n = 0;
		const { calls } = renderWithApp(<Probe />, {
			"POST /api/upload": () => {
				n += 1;
				if (n === 1) setAtlasGen(2); // (another atlas opens while the first file goes out)
				return { path: `C:/up/${n}.png` };
			},
			"POST /api/screenshots": { queued: 1 },
		});
		await actions.dropFiles([shot("a.png"), shot("b.png"), shot("c.png")]);
		expect(calls.filter((c) => c.path === "/api/upload")).toHaveLength(1);
		expect(calls.find((c) => c.path === "/api/screenshots")).toBeUndefined();
	});
});
