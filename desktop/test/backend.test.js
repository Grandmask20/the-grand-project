"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const { test } = require("node:test");
const { backendCommand, backendEnv, backendPath, findUrl, handedOver, semverOf } = require("../lib/backend");

test("the frozen program is in resources/backend, with .exe on Windows", () => {
	assert.equal(backendPath("R", "win32"), path.join("R", "backend", "grand-project.exe"));
	assert.equal(backendPath("R", "darwin"), path.join("R", "backend", "grand-project"));
});

test("packaged: the frozen program; else the repo's Python", () => {
	const packaged = backendCommand({ packaged: true, resourcesPath: "R", platform: "win32", repo: "X" });
	assert.deepEqual(packaged.args, ["--no-browser"]);
	assert.equal(packaged.cwd, path.join("R", "backend"));
	const dev = backendCommand({ packaged: false, resourcesPath: "R", platform: "darwin", repo: "X" });
	assert.deepEqual(dev, { cmd: "python3", args: ["-m", "grand_project", "--no-browser"], cwd: "X" });
	assert.equal(backendCommand({ packaged: false, platform: "linux", repo: "X", python: "py" }).cmd, "py");
});

test("the program keeps the atlases in the desktop app's folder, never a test copy's", () => {
	const env = backendEnv({ PATH: "p", GRAND_PROJECT_USER_DATA: "t" }, "H");
	assert.equal(env.GRAND_PROJECT_HOME, "H");
	assert.equal(env.GRAND_PROJECT_DESKTOP, "1");
	assert.equal(env.PATH, "p");
	assert.equal("GRAND_PROJECT_USER_DATA" in env, false);
});

test("the page's address is found in what the program prints", () => {
	assert.equal(
		findUrl("The Grand Project release 1.3.1: http://127.0.0.1:8766/  (Ctrl+C to quit)\n"),
		"http://127.0.0.1:8766/",
	);
	assert.equal(findUrl("loading…"), null);
	assert.equal(handedOver("The Grand Project is already running: http://127.0.0.1:8765/"), true);
	assert.equal(handedOver("The Grand Project v1.30: http://127.0.0.1:8765/"), false);
});

test("a release tag becomes semver; anything else is refused", () => {
	assert.equal(semverOf("v1.3"), "1.3.0");
	assert.equal(semverOf("v1.3.1"), "1.3.1");
	assert.equal(semverOf("1.30"), "1.30.0");
	assert.equal(semverOf("v1.3-beta"), null);
	assert.equal(semverOf(""), null);
});
