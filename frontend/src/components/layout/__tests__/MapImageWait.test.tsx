import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MapImageWait } from "@/components/layout/MapImageWait";
import type { Parts } from "@/domain/app/Parts";
import { PART_QUIET_S } from "@/hooks/app/UseParts";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const withImage = (map_image: NonNullable<Parts["parts"]["map_image"]>): Parts => ({
	generation: 1,
	parts: { map_image },
});

describe("MapImageWait", () => {
	afterEach(resetStore);

	it("says why the map image failed (it waited on 'Building the map image…' for good)", async () => {
		renderWithApp(<MapImageWait />, {
			"GET /api/parts": withImage({ state: "failed", error: "OSError: disk full", quiet: 0 }),
		});
		expect(await screen.findByText(/could not be built: OSError: disk full/)).toBeInTheDocument();
	});

	it("names a build that has stopped making progress, and stays quiet about one that is working", async () => {
		const stalled = renderWithApp(<MapImageWait />, {
			"GET /api/parts": withImage({ state: "building", error: null, quiet: PART_QUIET_S + 5 }),
		});
		expect(await screen.findByText(/no progress for 35 s/)).toBeInTheDocument();
		stalled.unmount();
		renderWithApp(<MapImageWait />, {
			"GET /api/parts": withImage({ state: "building", error: null, quiet: 2 }),
		});
		expect(await screen.findByText("Building the map image…")).toBeInTheDocument();
	});
});
