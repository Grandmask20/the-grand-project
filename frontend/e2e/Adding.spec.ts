import { copyFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { E2E_ATLAS, get, linesOf, name, post, RUN, shots, state, useAtlas, waitIdle } from "./AppApi";

/**
 * Adding screenshots while the page is in use: the detection runs in worker processes and a background job, the page
 * and the rest of the app must keep working beside it and see what it did. Made-up screenshots (tests/e2e_atlas.py):
 * the detection, the job queue, auto-add and the page all run as with real ones, they just never line up, so the
 * first defines a new atlas and the others are "not placed". The real ones: RealAdding.spec.ts.
 */

test.describe.configure({ mode: "serial" });

const pageErrors: string[] = [];

test.beforeEach(async ({ page }) => {
	page.on("pageerror", (e) => pageErrors.push(e.message));
});

test.afterEach(() => {
	expect(pageErrors).toEqual([]);
	pageErrors.length = 0;
});

test.afterAll(async ({ browser }) => {
	// the next spec works on the hand-made atlas again
	const page = await browser.newPage();
	await useAtlas(page, E2E_ATLAS);
	await page.close();
});

test("adds a batch through File › Add screenshots; the page stays usable while it detects", async ({ page }) => {
	await useAtlas(page, join(RUN, `adding-${test.info().retry}`), true); // a retry starts a new atlas
	const batch = shots("batch");
	expect(batch).toHaveLength(6);

	await page.getByRole("button", { name: "File" }).click();
	await page.getByRole("menuitem", { name: "Add screenshots…" }).click();
	const dialog = page.getByRole("dialog", { name: "Add atlas screenshots" });
	await dialog.getByRole("textbox", { name: "Folder" }).fill(join(RUN, "shots", "batch"));
	await dialog.getByRole("textbox", { name: "Folder" }).press("Enter");
	await expect(dialog.getByText(name(batch[0]))).toBeVisible();
	await dialog.getByRole("button", { name: "Select all" }).click();
	await dialog.getByRole("button", { name: "Open" }).click();

	// while it works: the progress box, and the app answers the page at once (the detection runs beside it)
	await expect(page.getByRole("status").filter({ hasText: /detecting|adding|placing|check/i })).toBeVisible();
	let slowest = 0;
	let whileBusy = 0;
	for (let i = 0; i < 6; i++) {
		const t = Date.now(); // the state read that decides the loop is timed too (CodeRabbit)
		const busy = (await state(page)).busy;
		await get(page, "/api/search?q=%230");
		await get(page, "/api/bookmarks");
		slowest = Math.max(slowest, Date.now() - t);
		if (!busy) break;
		whileBusy++;
		await page.waitForTimeout(400);
	}
	expect(whileBusy, "measured while the job ran").toBeGreaterThan(0);
	expect(slowest, "the page waited on the job").toBeLessThan(5_000);
	await page.getByRole("button", { name: "Log", exact: true }).click(); // (the log drawer, from the status line)
	await expect(page.getByText(/adding: 6 screenshot\(s\)/)).toBeVisible();

	const s = await waitIdle(page);
	// every screenshot detected once, none failed; the first defines the atlas, the others don't line up
	for (const f of batch)
		expect(
			linesOf(s.log, f).filter((l) => / \d+ maps, \d+ icons/.test(l)),
			name(f),
		).toHaveLength(1);
	expect(s.log.filter((l) => /detection failed/.test(l))).toEqual([]);
	expect(s.atlas?.shots).toBe(1);
	expect(s.log.filter((l) => /^\S+\s+NOT ADDED: /.test(l))).toHaveLength(5);
	await expect(page.getByRole("status").filter({ hasText: /detecting/i })).toBeHidden();
	await expect(page.getByText(/1\s+screenshots/)).toBeVisible();
	await page.screenshot({ path: test.info().outputPath("after-batch.png") });
});

test("two batches sent back to back run one after the other, nothing lost or done twice", async ({ page }) => {
	await page.goto("/");
	const a = shots("queued_a");
	const b = shots("queued_b");
	expect((await post(page, "/api/screenshots", { paths: a })).status).toBe(200);
	expect((await post(page, "/api/screenshots", { paths: b })).status).toBe(200);
	expect((await state(page)).busy).toBe(true);
	const s = await waitIdle(page);
	const starts = s.log.flatMap((l, i) => (/adding: 3 screenshot\(s\)/.test(l) ? [{ i, l }] : []));
	expect(starts).toHaveLength(2);
	expect(starts[0].l).toContain(name(a[0])); // in the order sent
	expect(starts[1].l).toContain(name(b[0]));
	for (const f of [...a, ...b])
		expect(
			linesOf(s.log, f).filter((l) => / \d+ maps, \d+ icons/.test(l)),
			name(f),
		).toHaveLength(1);
	expect(s.log.filter((l) => /detection failed/.test(l))).toEqual([]);
});

test("while adding, opening another atlas and undo wait; afterwards they work", async ({ page }) => {
	await page.goto("/");
	const late = shots("late");
	expect((await post(page, "/api/screenshots", { paths: late })).status).toBe(200);
	const open = await post(page, "/api/atlas/open", { path: E2E_ATLAS });
	expect(open.status).toBeGreaterThanOrEqual(400);
	expect(String(open.body?.error)).toMatch(/wait until the screenshots being added are done/);
	const undo = await post(page, "/api/undo");
	expect(undo.status).toBeGreaterThanOrEqual(400);
	expect((await state(page)).atlas?.path).toContain("adding"); // still the same atlas
	const s = await waitIdle(page);
	expect(s.log.filter((l) => /detection failed/.test(l))).toEqual([]);
	// the page's own Undo now (asks first)
	await page.reload();
	await page.getByRole("button", { name: "Undo" }).click();
	await page.getByRole("dialog").getByRole("button", { name: "Undo" }).click();
	await expect.poll(async () => (await waitIdle(page)).atlas?.shots).toBe(0);
});

test("auto-add picks up screenshots saved while it watches", async ({ page }) => {
	await page.goto("/");
	const watched = join(RUN, "watched");
	expect((await post(page, "/api/watch/folder", { folder: watched })).status).toBe(200);
	expect((await post(page, "/api/watch", { on: true })).status).toBe(200);
	// (Auto-add is a page of the Atlases tab)
	await page.getByRole("tab", { name: "Atlases" }).click();
	await page.getByRole("tab", { name: "Auto-add" }).click();
	const files = shots("watch");
	for (const f of files) copyFileSync(f, join(watched, name(f)));
	// seen twice with the same size, then added (WATCH_POLL_MS apart)
	await expect
		.poll(async () => (await state(page)).log.some((l) => /auto-add: 3 new screenshot\(s\)/.test(l)), {
			timeout: 30_000,
		})
		.toBe(true);
	const s = await waitIdle(page);
	for (const f of files)
		expect(
			linesOf(s.log, f).filter((l) => / \d+ maps, \d+ icons/.test(l)),
			name(f),
		).toHaveLength(1);
	// the atlas is empty after the undo: the first one starts it, the others don't line up and wait, listed in the
	// Auto-add tab to place by hand
	expect(s.atlas?.shots).toBe(1);
	expect(s.waiting).toHaveLength(2);
	const waiting = s.waiting.map((w) => w.name);
	expect(files.map(name).filter((n) => !waiting.includes(n))).toHaveLength(1);
	await expect(page.getByText(waiting[0]).first()).toBeVisible();
	expect((await post(page, "/api/watch", { on: false })).status).toBe(200);
});
