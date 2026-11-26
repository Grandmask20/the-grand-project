"use strict";
/**
 * The desktop app's side of the program (main.js): where the frozen program is, what it is started with, and the page's
 * address it prints. Kept apart from Electron so the tests run on plain Node (node --test).
 */
const path = require("node:path");

/** The page's address the program prints when it serves (app/server.py), or when it finds itself already running. */
const URL_RE = /http:\/\/127\.0\.0\.1:\d+\//;

/**
 * The frozen program inside the packaged app (PyInstaller's folder: desktop/grand-project.spec, copied to
 * resources/backend by electron-builder's extraResources).
 * @param {string} resourcesPath Electron's process.resourcesPath.
 * @param {string} platform process.platform.
 * @returns {string}
 */
function backendPath(resourcesPath, platform) {
	return path.join(resourcesPath, "backend", platform === "win32" ? "grand-project.exe" : "grand-project");
}

/**
 * The command that starts the program: the frozen one in the packaged app, else the repo's Python (npm start in
 * desktop/, for trying the desktop app without packaging it).
 * @param {{packaged: boolean, resourcesPath: string, platform: string, repo: string, python?: string}} o
 * @returns {{cmd: string, args: string[], cwd: string}}
 */
function backendCommand(o) {
	if (o.packaged) {
		const cmd = backendPath(o.resourcesPath, o.platform);
		return { cmd, args: ["--no-browser"], cwd: path.dirname(cmd) };
	}
	const python = o.python || (o.platform === "win32" ? "python" : "python3");
	return { cmd: python, args: ["-m", "grand_project", "--no-browser"], cwd: o.repo };
}

/**
 * The program's environment: the desktop app's data folder for the atlases and settings (its program folder is
 * replaced by every update: grand_project/paths.py), and the in-app update left to the desktop app.
 * @param {Record<string, string | undefined>} base The desktop app's own environment.
 * @param {string} home Electron's userData folder.
 * @returns {Record<string, string | undefined>}
 */
function backendEnv(base, home) {
	const env = { ...base, GRAND_PROJECT_HOME: home, GRAND_PROJECT_DESKTOP: "1", PYTHONUNBUFFERED: "1" };
	delete env.GRAND_PROJECT_USER_DATA; // (a test copy's settings folder would win over the desktop app's own)
	return env;
}

/**
 * The page's address in what the program printed so far, or null.
 * @param {string} text
 * @returns {string | null}
 */
function findUrl(text) {
	const m = URL_RE.exec(text);
	return m ? m[0] : null;
}

/**
 * The program found another copy of itself already serving and handed over to it (it then stops: app/server.py's
 * reuse_running): the page is that copy's, and the desktop app stops it when it closes.
 * @param {string} text
 * @returns {boolean}
 */
function handedOver(text) {
	return /already running/i.test(text);
}

/**
 * electron-updater's version (semver) of a release tag: "v1.3" → "1.3.0", "v1.3.1" → "1.3.1".
 * @param {string} tag
 * @returns {string | null} null when the tag isn't a release number.
 */
function semverOf(tag) {
	const m = /^v?(\d+)\.(\d+)(?:\.(\d+))?$/.exec(String(tag).trim());
	return m ? `${Number(m[1])}.${Number(m[2])}.${Number(m[3] ?? 0)}` : null;
}

module.exports = { backendCommand, backendEnv, backendPath, findUrl, handedOver, semverOf };
