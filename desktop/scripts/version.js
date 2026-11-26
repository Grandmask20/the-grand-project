"use strict";
// node scripts/version.js v1.3.1 → 1.3.1: the desktop app's version for a release tag (CI: desktop.yml)
const { semverOf } = require("../lib/backend");

const v = semverOf(process.argv[2] || "");
if (!v) {
	console.error(`not a release number: ${process.argv[2] || "(none)"} (like v1.3 or v1.3.1)`);
	process.exit(1);
}
console.log(v);
