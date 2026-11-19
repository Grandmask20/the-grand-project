import { screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import type { Parts } from "@/domain/app/Parts";
import { PARTS_ASK_MS, useParts } from "@/hooks/app/UseParts";
import { state } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const parts: Parts = {
	generation: 3,
	parts: {
		map_image: { state: "ready", error: null, quiet: 1 },
		model: { state: "building", error: null, quiet: 2 },
	},
};

function Probe({ watching }: { watching: boolean }) {
	const q = useParts(watching);
	// "loading" until the answer is in: "none yet" only for an answer given but not usable (it matched before the
	// answer came, so the generation check went untested: CodeRabbit)
	if (!q.isSuccess) return <p>loading</p>;
	return <p>{q.data ? `${q.data.parts.map_image?.state} / ${q.data.parts.model?.state}` : "none yet"}</p>;
}

/** The cover: watching until the map is shown. */
function Cover() {
	const [shown, setShown] = useState(false);
	return (
		<>
			<Probe watching={!shown} />
			<button type="button" onClick={() => setShown(true)}>
				show
			</button>
		</>
	);
}

describe("useParts", () => {
	afterEach(resetStore);

	it("reads how far the map's parts are", async () => {
		renderWithApp(<Probe watching={false} />, {
			"GET /api/state": { ...state, generation: 3 },
			"GET /api/parts": parts,
		});
		expect(await screen.findByText("ready / building")).toBeInTheDocument();
	});

	it("gives nothing for another atlas than the one the page shows", async () => {
		// the page shows generation 1 (the fixtures' state); a part that failed for atlas 3 skipped the new cover
		renderWithApp(<Probe watching={false} />, {
			"GET /api/state": { ...state, generation: 1 },
			"GET /api/parts": parts,
		});
		expect(await screen.findByText("none yet")).toBeInTheDocument();
	});

	it("asks again on a schedule only while the loading cover watches", async () => {
		const { user, queryClient } = renderWithApp(<Cover />, {
			"GET /api/state": { ...state, generation: 3 },
			"GET /api/parts": parts,
		});
		await screen.findByText("ready / building");
		const observer = () => queryClient.getQueryCache().find({ queryKey: AppQueryKeys.parts })?.observers[0];
		expect(observer()?.options).toMatchObject({ refetchInterval: PARTS_ASK_MS });
		await user.click(screen.getByRole("button", { name: "show" }));
		expect(observer()?.options).toMatchObject({ refetchInterval: false });
	});
});
