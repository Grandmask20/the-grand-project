# atlas-tests: standard atlases for detector numbers

Fixed atlases to measure the detector against, so a change (or a new detector like RF-DETR) can be compared
with the same numbers every time.

## The res_* atlases

The same 3 screenshots, taken at the same 3 bookmarked spots on the atlas, at 8 screen resolution and in-game
render-scale settings. The screenshots overlap in the middle: 1 shows the centres of 1 and 2, 2 shows all three,
3 shows the centres of 2 and 3.

| atlas | screen | render scale | renders at |
|---|---|---|---|
| res_4k_100 (reference) | 3840x2160 | 100% | 4K |
| res_4k_67 | 3840x2160 | 67% | 1440p |
| res_4k_50 | 3840x2160 | 50% | 1080p |
| res_4k_33 | 3840x2160 | 33% | 720p |
| res_1440_100 | 2560x1440 | 100% | 1440p |
| res_1440_50 | 2560x1440 | 50% | 720p |
| res_1080_100 | 1920x1080 | 100% | 1080p (what the detector was trained on) |
| res_1080_67 | 1920x1080 | 67% | 720p |

Screenshots are scaled to 1080p on read (`core.read_screenshot`). Icons are UI and always render at 100%; the
render scale only changes map nodes, terrain and paths, so low render scales mostly cost map nodes and paths.

Each folder is a normal atlas (atlas folder = screenshot folder): `atlas.json`, the cached detections in
`atlas_frames/` and the map pictures in `atlas_files/`. Open one in the viewer with File > Open atlas.

Built with v1.15 (`develop` + PR #27; the detector is the same as develop) and the shipped
`references/atlas_references.sqlite3` (same models as the private database: maps / badges / towers trained
2026-11-15, fortress 2026-11-12; 627 icon pictures).

## Numbers (v1.15)

| atlas | maps | paths | icons | landmarks | maps found vs 4K 100% | icons found | paths found |
|---|---:|---:|---:|---|---:|---:|---:|
| res_4k_100 | 123 | 112 | 10 | City 1, Tower 2 | (reference) | | |
| res_4k_67 | 118 | 106 | 9 | City 1, Tower 2 | 113 / 123 (92%) | 9 / 10 | 87 / 112 (78%) |
| res_4k_50 | 120 | 106 | 10 | City 1, Tower 2 | 114 / 123 (93%) | 10 / 10 | 91 / 112 (81%) |
| res_4k_33 | 100 | 44 | 10 | City 1, Tower 2 | 96 / 123 (78%) | 9 / 10 | 36 / 112 (32%) |
| res_1440_100 | 118 | 99 | 14 | City 1, Tower 2 | 113 / 123 (92%) | 7 / 10 | 81 / 112 (72%) |
| res_1440_50 | 100 | 35 | 14 | City 2, Tower 1 | 90 / 123 (73%) | 7 / 10 | 24 / 112 (21%) |
| res_1080_100 | 120 | 124 | 8 | City 1, Tower 3 | 116 / 123 (94%) | 5 / 10 | 100 / 112 (89%) |
| res_1080_67 | 95 | 37 | 5 | City 1, Tower 3 | 92 / 123 (75%) | 4 / 10 | 26 / 112 (23%) |

All 3 screenshots placed in every atlas. `baseline_v1.15.json` holds the full numbers (map nodes by status,
icon types, landmarks, per-screenshot detections). Rebuilding from scratch gives exactly the same numbers.

What stands out:

- **Render scale matters, screen size much less.** At 100% render (4K, 1440p, 1080p) and at 4K 67% / 50%,
  92-94% of the reference map nodes are found. At 720p-equivalent render (4K 33%, 1440p 50%, 1080p 67%) it drops to
  73-78%, and **paths collapse to 21-32%**: blurred dashes stop being traced.
- **Icons are a small sample** (10 in the reference). Icons are UI (always rendered at 100%), yet 1440p and 1080p
  find fewer of the reference's icons than the 4K sets, and 1440p has 14 against 10: worth a look (duplicates or
  extra names).
- 1440p 50% sees 2 cities against 1 everywhere else; 1080p sees 3 towers against 2.

## Measuring a detector change

From a checkout of the repo (after `git lfs pull --include="atlas_test_data/**"` this folder is
`atlas_test_data/res_atlases`):

```
python atlas_test_data/res_atlases/score_atlases.py --rebuild --compare atlas_test_data/res_atlases/baseline_v1.15.json
```

`--rebuild` re-detects and rebuilds every atlas here with that checkout's detector (in a temp copy, then copied
back over the atlas files; the screenshots are never changed). Without it, the atlases are scored as they are.
`--save my_run.json` keeps a run to compare with later.

What the numbers are:

- **maps / paths / icons / landmarks**: what the atlas holds after the atlas-wide check (as the viewer shows it,
  removed map nodes left out).
- **per screenshot** (in the saved JSON): what the detector itself found in each screenshot.
- **vs 4K 100%**: how many of this atlas's map nodes / icons / paths match the reference atlas (same spot within
  15 units after lining the atlases up; icons also the same name; paths between the same two matched map nodes),
  and how many of the reference's it found. The reference isn't hand-checked truth, just the sharpest version of
  the same three views, so "found 100%" means "as good as at 4K 100%".
