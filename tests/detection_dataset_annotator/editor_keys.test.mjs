// The box editor's key matching and guess styling (component/annotator.js), run by test_editor_keys.py with
// `node --test`. The palette is the one Python builds (label_palette), passed in ANNOTATOR_TEST_PALETTE.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  closestHandle,
  coordinateValue,
  finderKeyActs,
  finderPick,
  isGuess,
  keepUnmoved,
  labelForKey,
  plainKeyTarget,
  relabelled,
  repeatIgnored,
  scaledSide,
  wheelPixels,
} from "../../tools/detection_dataset_annotator/component/annotator.js";

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

test("the nearest handle in reach resizes, so a small box can be resized from any corner", () => {
  const small = { x: 100, y: 100, w: 8, h: 8 }; // every handle is within reach (9 px) of every other
  assert.equal(closestHandle({ x: 108, y: 108 }, [small], 9).handle, "se");
  assert.equal(closestHandle({ x: 101, y: 107 }, [small], 9).handle, "sw");
  assert.equal(closestHandle({ x: 104, y: 99 }, [small], 9).handle, "n");
  assert.equal(closestHandle({ x: 130, y: 130 }, [small], 9), null);
  const other = { x: 107, y: 107, w: 50, h: 50 };
  assert.equal(closestHandle({ x: 107, y: 107 }, [small, other], 9).box, other); // its corner is right there
});

test("wheel deltas in lines or pages count in pixels", () => {
  assert.equal(wheelPixels(100, 0, 800), 100);
  assert.equal(wheelPixels(3, 1, 800), 120); // Firefox's notch: about one 100 px step, as Chrome's
  assert.equal(wheelPixels(-1, 2, 800), -800);
});

test("an emptied coordinate is no 0", () => {
  assert.equal(coordinateValue(""), null);
  assert.equal(coordinateValue("   "), null);
  assert.equal(coordinateValue("abc"), null);
  assert.equal(coordinateValue("0"), 0);
  assert.equal(coordinateValue(" 12.5 "), 12.5);
});

test("a held key reviews or moves to another screenshot once; arrows, undo and zoom repeat", () => {
  for (const shortcut of ["Enter", "n", "p", "[", "]"]) assert.equal(repeatIgnored(shortcut), true, shortcut);
  for (const shortcut of ["ArrowLeft", "z", "+", "-", ",", ".", "j"]) assert.equal(repeatIgnored(shortcut), false);
  // N and P with Shift: the shortcut is the lower-case letter
  assert.equal(repeatIgnored(plainKeyTarget(palette, { key: "N", code: "KeyN", shiftKey: true }).shortcut), true);
});

test("the finder's Enter uses its first match, nothing while it is empty", () => {
  const shown = [{ name: "tower" }, { name: "hall" }];
  assert.equal(finderPick(shown, "to").name, "tower");
  assert.equal(finderPick(shown, ""), null);
  assert.equal(finderPick([], "zzz"), null);
});

test("the label finder leaves Enter and Esc to an input method composing a word", () => {
  assert.equal(finderKeyActs({ key: "Enter", isComposing: false, keyCode: 13 }), true);
  assert.equal(finderKeyActs({ key: "Escape", isComposing: false, keyCode: 27 }), true);
  assert.equal(finderKeyActs({ key: "Enter", isComposing: true, keyCode: 13 }), false); // picks the composed word
  assert.equal(finderKeyActs({ key: "Enter", isComposing: false, keyCode: 229 }), false); // (Safari's end of one)
  assert.equal(finderKeyActs({ key: "a", isComposing: false, keyCode: 65 }), false); // typed into the finder
});

test("shrinking a box never grows a side below the drawn-box minimum", () => {
  assert.equal(scaledSide(1, -1), 1); // a 1 px side stays (the 2 px floor made it grow)
  assert.equal(scaledSide(3, -1), 1);
  assert.equal(scaledSide(3, -5), 1);
  assert.equal(scaledSide(1, 1), 3);
});

test("a label changes only the boxes that have another one", () => {
  const boxes = [
    { id: "a", label: "tower", source: "classical" },
    { id: "b", label: "hall", source: "classical" },
  ];
  assert.deepEqual(
    relabelled(boxes, "tower").map((box) => box.id),
    ["b"],
  );
});

test("a drag that ends where it began is no edit of that box", () => {
  // the drag marked both edited; one moved, the other was held against the image edge and stayed
  const before = [
    { id: "a", x: 10, y: 10, w: 40, h: 40, source: "classical", score: 0.9 },
    { id: "b", x: 0, y: 0, w: 40, h: 40, source: "biome_guess", score: 0.5 },
  ];
  const boxes = [
    { id: "a", x: 12, y: 10, w: 40, h: 40, source: "manual", score: null },
    { id: "b", x: 0, y: 0, w: 40, h: 40, source: "manual", score: null },
  ];
  assert.equal(keepUnmoved(boxes, before), true);
  assert.deepEqual([boxes[0].source, boxes[1].source, boxes[1].score], ["manual", "biome_guess", 0.5]);
  const still = [{ ...before[0], source: "manual", score: null }];
  assert.equal(keepUnmoved(still, before), false); // nothing moved: no undo step, no autosave
  assert.equal(still[0].source, "classical");
});
