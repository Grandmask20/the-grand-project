import { afterEach, describe, expect, it, vi } from "vitest";
import { download } from "@/utils/Download";

describe("Download", () => {
	afterEach(() => {
		vi.useRealTimers();
		vi.restoreAllMocks();
	});

	it("saves text through a clicked link and frees it afterwards", () => {
		vi.useFakeTimers();
		const made: Blob[] = [];
		URL.createObjectURL = vi.fn((b: Blob) => {
			made.push(b);
			return "blob:x";
		});
		URL.revokeObjectURL = vi.fn();
		const clicked: HTMLAnchorElement[] = [];
		vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
			clicked.push(this);
		});
		download("a,b\n1,2\n", "frames.csv", "text/csv");
		expect(clicked).toHaveLength(1);
		expect(clicked[0].download).toBe("frames.csv");
		expect(clicked[0].href).toBe("blob:x");
		expect(made[0].type).toBe("text/csv");
		expect(made[0].size).toBe("a,b\n1,2\n".length);
		expect(document.querySelector("a[download]")).toBeNull(); // the link is gone again
		expect(URL.revokeObjectURL).not.toHaveBeenCalled();
		vi.advanceTimersByTime(1000);
		expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:x");
	});

	it("saves a blob as it is", () => {
		URL.createObjectURL = vi.fn(() => "blob:y");
		URL.revokeObjectURL = vi.fn();
		vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
		const blob = new Blob(["png"], { type: "image/png" });
		download(blob, "map.png");
		expect(URL.createObjectURL).toHaveBeenCalledWith(blob);
	});
});
