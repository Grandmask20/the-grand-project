import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { E2E_ATLAS, get, linesOf, name, post, RUN, shots, state, useAtlas, waitIdle } from "./AppApi";

/**
 * Adding real crawl screenshots (test data, Git LFS; skipped without it): they line up, so the atlas grows. A
 * second batch is sent while the first is still being detected, as auto-add does when screenshots keep coming.
 */

test.describe.configure({ mode: "serial" });

const crawl = shots("crawl");
test.skip(crawl.length < 8, 'no test data (git lfs pull --include="atlas_test_data/**")');

test.afterAll(async ({ browser }) => {
	const page = await browser.newPage();
	await useAtlas(page, E2E_ATLAS);
	await page.close();
});

test("two batches of real screenshots, the second sent while the first is detected, build one atlas", async ({
	page,
}) => {
	test.setTimeout(480_000); // detecting 8 real screenshots may take its 300 s, then the checks (CodeRabbit)
	const errors: string[] = [];
	page.on("pageerror", (e) => errors.push(e.message));
	await useAtlas(page, join(RUN, `real-${test.info().retry}`), true); // a retry starts a new atlas
	const first = crawl.slice(0, 4);
	const second = crawl.slice(4, 8);

	await page.getByRole("button", { name: "File" }).click();
	await page.getByRole("menuitem", { name: "Add screenshots…" }).click();
	const dialog = page.getByRole("dialog", { name: "Add atlas screenshots" });
	await dialog.getByRole("textbox", { name: "Folder" }).fill(join(RUN, "crawl"));
	await dialog.getByRole("textbox", { name: "Folder" }).press("Enter");
	for (const f of first) await dialog.getByRole("button", { name: new RegExp(name(f).replace(".", "\\.")) }).click();
	await dialog.getByRole("button", { name: "Open" }).click();
	await expect.poll(async () => (await state(page)).busy).toBe(true);
	expect((await post(page, "/api/screenshots", { paths: second })).status).toBe(200);

	const s = await waitIdle(page, 300_000);
	expect(s.log.filter((l) => /detection failed/.test(l))).toEqual([]);
	for (const f of crawl)
		expect(
			linesOf(s.log, f).filter((l) => / \d+ maps, \d+ icons/.test(l)),
			name(f),
		).toHaveLength(1);
	// every screenshot accounted for once: in the atlas, waiting, or not placed
	const notPlaced = s.log.filter((l) => /NOT ADDED: /.test(l));
	expect((s.atlas?.shots ?? 0) + s.waiting.length + notPlaced.length).toBe(8);
	expect(s.atlas?.shots ?? 0).toBeGreaterThanOrEqual(4);
	expect(s.atlas?.maps ?? 0).toBeGreaterThan(0);
	expect(s.undo.length).toBeGreaterThanOrEqual(1); // a batch that placed something can be undone

	// the page shows the new maps: the map, Find, the replay of how it was made
	await page.reload();
	await expect(page.getByText(new RegExp(`${s.atlas?.maps} maps`))).toBeVisible();
	await page.getByRole("textbox", { name: "Find" }).fill("#0");
	await expect(page.getByRole("button", { name: "Map #0", exact: true })).toBeVisible();
	const plan = await post(page, "/api/replay/open");
	expect(plan.status).toBe(200);
	expect(Number(plan.body?.n_steps)).toBeGreaterThan(0);
	await post(page, "/api/replay/close");
	await page.screenshot({ path: test.info().outputPath("real-atlas.png") });

	// undo takes the second batch back
	const before = s.atlas?.shots ?? 0;
	expect((await post(page, "/api/undo")).status).toBe(200);
	const after = await waitIdle(page);
	expect(after.atlas?.shots ?? 0).toBeLessThan(before);
	expect((await get<{ results?: unknown[] }>(page, "/api/search?q=%230")).results).toBeDefined();
	expect(errors).toEqual([]);
});
