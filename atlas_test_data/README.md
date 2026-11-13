# Test data (trimmed)

A small part of the author's own test set, so the tests and `atlas_detect.py score` can run on any computer:

| Folder | What |
|---|---|
| `screenshots/random_samples/`, `truth/` | 10 hand-labelled screenshots and their truth |
| `screenshots/ocean/`, `truth_ocean/` | 10 hand-labelled ocean (Expedition) screenshots |
| `screenshots/crawl/` | the first 110 screenshots of a crawl across the atlas, plus the small atlas's 5 |
| `crawl_atlas/`, `small_atlas/` | finished atlases of those screenshots, with their cached detections |

It is stored with Git LFS and is NOT downloaded by a normal clone (see `.lfsconfig`). To get it:

    git lfs pull --include="atlas_test_data/**"

Training needs more data (tower shots, painted walls, the arborist rounds); that is not included.
