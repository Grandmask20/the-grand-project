/** After the browser tests: ask the app to quit, so it saves (and, under coverage, writes its data). */
export default async function teardown(): Promise<void> {
	const port = Number(process.env.E2E_PORT);
	try {
		await fetch(`http://127.0.0.1:${port}/api/quit`, { method: "POST", headers: { "X-Grand": "1" } });
		await new Promise((r) => setTimeout(r, 1500));
	} catch {
		// already gone
	}
}
