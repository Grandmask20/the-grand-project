import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, createHttp, StaleError, setAtlasGen } from "@/api/Http";

const reply = (status: number, body: unknown, gen?: number) =>
	new Response(body === null ? "" : JSON.stringify(body), {
		status,
		headers: { "Content-Type": "application/json", ...(gen === undefined ? {} : { "X-Atlas-Gen": String(gen) }) },
	});

describe("createHttp", () => {
	it("gets JSON with its query", async () => {
		const fetcher = vi.fn().mockResolvedValue(reply(200, { ok: 1 }));
		const http = createHttp("http://app", fetcher);
		expect(await http.get("/api/search", { q: "a b", skip: undefined })).toEqual({ ok: 1 });
		expect(fetcher).toHaveBeenCalledWith("http://app/api/search?q=a+b", { method: "GET" });
	});

	it("sends changes with the X-Grand header", async () => {
		const fetcher = vi.fn().mockResolvedValue(reply(200, null));
		await createHttp("", fetcher).send("POST", "/api/undo", { a: 1 });
		const [, init] = fetcher.mock.calls[0];
		expect(init.headers["X-Grand"]).toBe("1");
		expect(init.body).toBe('{"a":1}');
	});

	it("turns the app's errors into ApiError", async () => {
		const http = createHttp("", vi.fn().mockResolvedValue(reply(409, { error: "already a bookmark" })));
		await expect(http.send("POST", "/api/bookmarks", {})).rejects.toEqual(new ApiError("already a bookmark", 409));
		const down = createHttp("", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
		await expect(down.get("/api/state")).rejects.toMatchObject({ status: 0 });
	});

	describe("two atlases", () => {
		afterEach(() => setAtlasGen(null));

		it("sends the atlas the page draws with every change", async () => {
			setAtlasGen(4);
			const fetcher = vi.fn().mockResolvedValue(reply(200, null, 4));
			await createHttp("", fetcher).send("POST", "/api/bookmarks", {});
			expect(fetcher.mock.calls[0][1].headers["X-Atlas-Gen"]).toBe("4");
		});

		it("drops a refused change for the atlas open before as stale, not as an error", async () => {
			setAtlasGen(4);
			const http = createHttp(
				"",
				vi.fn().mockResolvedValue(reply(409, { error: "the atlas changed", stale: true }, 5)),
			);
			await expect(http.send("POST", "/api/lasso", {})).rejects.toBeInstanceOf(StaleError);
		});

		it("drops an answer that comes back after the page learned of another atlas", async () => {
			setAtlasGen(4);
			let answer: (r: Response) => void = () => undefined;
			const fetcher = vi.fn().mockReturnValue(new Promise<Response>((r) => (answer = r)));
			const got = createHttp("", fetcher).get("/api/search", { q: "Breach" });
			setAtlasGen(5); // the state said: another atlas is open
			answer(reply(200, { rows: [] }, 4));
			await expect(got).rejects.toBeInstanceOf(StaleError);
		});

		it("drops an answer the app gave for another atlas than the page draws", async () => {
			setAtlasGen(4);
			const http = createHttp("", vi.fn().mockResolvedValue(reply(200, { rows: [] }, 5)));
			await expect(http.get("/api/search")).rejects.toBeInstanceOf(StaleError);
		});

		it("keeps answers that belong to no atlas (the state itself, settings, switching)", async () => {
			setAtlasGen(4);
			const http = createHttp(
				"",
				vi.fn().mockImplementation(async () => reply(200, { ok: 1 }, 5)),
			);
			expect(await http.get("/api/state")).toEqual({ ok: 1 });
			expect(await http.send("POST", "/api/atlas/open", { path: "b" })).toEqual({ ok: 1 });
			expect(await http.send("PATCH", "/api/settings", {})).toEqual({ ok: 1 });
			await expect(http.send("POST", "/api/atlas/save")).rejects.toBeInstanceOf(StaleError);
		});
	});
});
