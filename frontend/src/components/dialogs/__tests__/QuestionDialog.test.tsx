import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { QuestionDialog } from "@/components/dialogs/QuestionDialog";
import type { AppState } from "@/domain/app/AppState";
import { state } from "@/test/Fixtures";
import { renderWithApp } from "@/test/RenderWithApp";

describe("QuestionDialog", () => {
	it("answers the app's question", async () => {
		const { user, calls, queryClient } = renderWithApp(<QuestionDialog />, { "POST /api/questions/5": { ok: true } });
		queryClient.setQueryData<AppState>(AppQueryKeys.state, {
			...state,
			questions: [
				{ id: 5, question: "a.png would be added, but the match is weak.", preview: { picture: 2, box: [0, 0, 1, 1] } },
			],
		});
		expect(await screen.findByText(/the match is weak/)).toBeInTheDocument();
		expect(screen.getByText(/It is shown and outlined on the map/)).toBeInTheDocument();
		await user.click(screen.getByRole("button", { name: "Yes" }));
		await waitFor(() => expect(calls.find((c) => c.path === "/api/questions/5")?.body).toEqual({ yes: true }));
		await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
	});
});
