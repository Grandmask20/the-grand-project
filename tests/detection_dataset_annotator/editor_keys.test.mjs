// The box editor's key matching and guess styling (component/annotator.js), run by test_editor_keys.py with
// `node --test`. The palette is the one Python builds (label_palette), passed in ANNOTATOR_TEST_PALETTE.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { isGuess, labelForKey, plainKeyTarget } from "../../tools/detection_dataset_annotator/component/annotator.js";

const { palette, guessSources } = JSON.parse(readFileSync(process.env.ANNOTATOR_TEST_PALETTE, "utf8"));

test("digits pick the node classes, hall and tower", () => {
  assert.equal(labelForKey(palette, "Digit1", false).name, "map_node");
  assert.equal(labelForKey(palette, "Digit2", false).name, "map_node_grass");
  assert.equal(labelForKey(palette, "Digit8", false).name, "map_node_faridun");
  assert.equal(labelForKey(palette, "Digit9", false).name, "hall");
  assert.equal(labelForKey(palette, "Digit0", false).name, "tower");
});

test("Shift+digits pick the citadels and the rest, by key code on any keyboard layout", () => {
  // Shift+1 types "!" on a US keyboard and "+" on a Swiss one: the code is Digit1 on both
  assert.equal(labelForKey(palette, "Digit1", true).name, "citadel_iron");
  assert.equal(labelForKey(palette, "Digit2", true).name, "citadel_stone");
  assert.equal(labelForKey(palette, "Digit3", true).name, "citadel_copper");
  assert.equal(labelForKey(palette, "Digit4", true).name, "breach_stronghold");
  assert.equal(labelForKey(palette, "Digit5", true).name, "reveal_button");
  assert.equal(labelForKey(palette, "Digit7", true).name, "path");
  assert.equal(labelForKey(palette, "Digit8", true).name, "fortress_wall");
});

test("a label's key wins over the character it types on other keyboard layouts", () => {
  // Swiss Shift+1 types "+" (zoom), German Shift+7 types "/" (the label finder), French 6 types "-" (zoom out)
  assert.equal(plainKeyTarget(palette, { key: "+", code: "Digit1", shiftKey: true }).label.name, "citadel_iron");
  assert.equal(plainKeyTarget(palette, { key: "/", code: "Digit7", shiftKey: true }).label.name, "path");
  assert.equal(plainKeyTarget(palette, { key: "-", code: "Digit6", shiftKey: false }).label.name, "map_node_ezomyte");
  // keys that are no label's keep their shortcut
  assert.deepEqual(plainKeyTarget(palette, { key: "+", code: "Equal", shiftKey: true }), { shortcut: "+" });
  assert.deepEqual(plainKeyTarget(palette, { key: "/", code: "Slash", shiftKey: false }), { shortcut: "/" });
  assert.deepEqual(plainKeyTarget(palette, { key: "J", code: "KeyJ", shiftKey: true }), { shortcut: "j" });
  assert.deepEqual(plainKeyTarget(palette, { key: "Escape", code: "Escape", shiftKey: false }), { shortcut: "Escape" });
});

test("keys without a label pick nothing", () => {
  assert.equal(labelForKey(palette, "KeyA", false), undefined);
  assert.equal(labelForKey(palette, "", false), undefined); // labels without a key have an empty code
});

test("every guess source is drawn dotted, nothing else is", () => {
  const guesses = new Set(guessSources);
  for (const source of ["city_guess", "biome_guess", "city_area_guess"]) {
    assert.ok(isGuess(guesses, { source }), source);
  }
  for (const source of ["classical", "manual", "icon_match", "icon_row", undefined]) {
    assert.ok(!isGuess(guesses, { source }), String(source));
  }
});
