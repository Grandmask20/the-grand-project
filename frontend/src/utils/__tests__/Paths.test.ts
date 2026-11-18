import { describe, expect, it } from "vitest";
import { ancestors } from "@/utils/Paths";

describe("ancestors", () => {
	it("splits drive, posix and network paths into their folders", () => {
		expect(ancestors("C:\\a\\b").map((a) => a.path)).toEqual(["C:\\", "C:\\a", "C:\\a\\b"]);
		expect(ancestors("/home/x").map((a) => a.path)).toEqual(["/", "/home", "/home/x"]);
		expect(ancestors("\\\\nas\\share\\shots")).toEqual([
			{ name: "\\\\nas\\share\\", path: "\\\\nas\\share\\" },
			{ name: "shots", path: "\\\\nas\\share\\shots" },
		]);
		expect(ancestors("\\\\nas\\share").map((a) => a.path)).toEqual(["\\\\nas\\share\\"]);
		expect(ancestors("drives")).toEqual([]);
		// a backslash inside a POSIX folder name is part of the name (it was taken for the separator)
		expect(ancestors("/home/maps\\old/atlas").map((a) => a.name)).toEqual(["/", "home", "maps\\old", "atlas"]);
		expect(ancestors("C:/a").map((a) => a.path)).toEqual(["C:/", "C:/a"]);
	});
});
