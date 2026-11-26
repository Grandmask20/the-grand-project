"""webmap.constants: the numbers of the map's tiles (MapLibre on the app's page)."""

from __future__ import annotations

# Raster tiles (the stitched map image): 256 px squares in the usual z/x/y layout, as JPEG. The map image is the
# most detailed level, so 1 tile px = 1 map image px there.
WEBMAP_TILE = 256
WEBMAP_JPEG_QUALITY = 85  # a 256 px terrain tile is ~25 KB at 85; PNG would be ~5x bigger for the same picture

# Vector tiles (Mapbox Vector Tile 2.1: map nodes, paths, landmarks, bookmarks).
WEBMAP_MVT_EXTENT = 4096  # tile coordinate range (the MVT default)
WEBMAP_MVT_BUFFER = 128  # extent units kept around each tile, so lines and dots crossing a tile edge draw whole

# Find's rows: a small picture of the ground around each map (the map node itself, user's mockup): this many atlas
# units each way from the map's middle (a map node's radius is ~8), this many px across.
WEBMAP_CROP_UNITS = 22.0
WEBMAP_CROP_PX = 64

# How far past the sharpest tiles the page lets the user zoom in (MapLibre stretches the last level).
WEBMAP_OVERZOOM = 1.5

# Colours (CSS) of the map node states (app.constants NODE_COL).
WEBMAP_STATUS_COLOUR = {
    "confirmed": "#28dcff",  # 2+ screenshots agree
    "icon": "#28dcff",  # placed from its icon
    "single": "#ffa000",  # one screenshot
    "disputed": "#ffa000",
    "doubtful": "#969696",
}
WEBMAP_NO_ICON_FILL = "#1b1e24"  # map node without an icon

# Sharp ground: levels past the map image are built from the screenshots at native resolution (core.sharp), by the
# app when the browser first asks for them, and kept on disk next to the atlas (<stem>_files/<stem>_sharp).
WEBMAP_SHARP_LEVEL = 2.0  # deepest level, px per atlas unit (zoomed in further, MapLibre stretches it)
WEBMAP_SHARP_MAX_FRAMES = 30  # screenshots warped at most per tile without a clean map
WEBMAP_SHARP_BUILDERS = 4  # tiles built at the same time (the browser asks for many at once)
# screenshot weights kept in memory (float16, ~0.25 MB each): 300 float32 ones held ~150 MB while panning
WEBMAP_SHARP_WEIGHTS = 128
# decoded screenshots the zoomed-in ground keeps for itself (~6 MB each): a tile's few, and its neighbours'. Reading
# through the placements' cache filled all 90 of it (~540 MB) when panning or opening Find's pictures
WEBMAP_SHARP_IMAGES = 12

# Map content icons: the in-game pictures (references/poe2db_icons: "full__" = whole badge, "inner__" = the art
# inside the ring), drawn on the map where each icon was seen.
WEBMAP_ICON_SPRITE = 64  # px per side of an icon picture
WEBMAP_ICON_UNITS = 26.0  # atlas units across an in-game icon (the detector's rim radius ICON_RIM_R reaches ~12.5 px)
WEBMAP_ICON_MIN_PX = 10.0  # icons are hidden while smaller than this on screen (too many to read zoomed out)
WEBMAP_ICON_RING = (87, 141, 176)  # BGR brass ring drawn around "inner__" art, like the game's badge rim

# Vector ground: land (where the screenshots show ground) and biome areas, as polygons. Each biome map is a disc;
# discs of the same biome close to each other are joined into one area.
WEBMAP_SHAPE_CELL = 16.0  # atlas units per grid cell the shapes are traced on
WEBMAP_BIOME_R = 140.0  # atlas units: disc around each map of a biome (maps are ~200-250 apart)
WEBMAP_BIOME_JOIN = 120.0  # atlas units: gaps up to about this between discs of one biome are closed
WEBMAP_BIOME_KEEP = 30.0  # atlas units: ground kept clear around a map outside a biome (a map's ring is ~24 across)
WEBMAP_BIOME_SMOOTH = 48.0  # atlas units: how far a biome area's cut edge is rounded off
WEBMAP_LAND_JOIN = 64.0  # atlas units: small holes in the land (fog specks between screenshots) are closed
WEBMAP_BIOME_COLOUR = {  # CSS colours; the city ones follow app.constants CITY_COL
    "Ezomyte": "#5ad25a",
    "Vaal": "#3296f0",
    "Faridun": "#82d7f0",
    "City": "#c8c8c8",  # a city of unknown type
    "Breach": "#eb50e1",
}
WEBMAP_LAND_COLOUR = "#2a2d30"

# 3D view: map node pillars (atlas units; one atlas unit is about one screenshot pixel). The landmark models'
# own sizes are in webmap/solids.py, next to their shapes.
WEBMAP_SOLID = {
    "map_r": 13.0,  # pillar radius (a map node's ring is ~24 px across in a screenshot)
    "map": 12.0,  # pillar height
    "boss_map": 24.0,  # pillar height of a map with a map boss icon
}
WEBMAP_BEAM_MIN = (
    300.0  # atlas units: a 3D shape this tall is a beam (hall, tower): icons stand under it, on the building
)
WEBMAP_TOWER_SAME = 150.0  # atlas units: a map node marked as a tower this close to a Tower landmark is that tower


WEBMAP_FOG_DARK = 14.0  # 0-255 grey: darker map image is the black fog at screenshots' edges (no ground: Colour by
# leaves it alone)
WEBMAP_MASK_MAX = 4096  # the ground mask's largest side in cells
