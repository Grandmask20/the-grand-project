"""app.tilesource: what the map's vector tiles and 3D scene are made from, as one record.

A job (adding screenshots, re-checking) holds the session lock for minutes, and the vector tiles used to be made
under that lock: every tile asked for meanwhile waited for the job, and the waiting requests took all the browser's
connections, so even the ground of a spot jumped to stayed black (user). Now every change to what the tiles show
puts a new record in place (MapImageMixin._source_sync), in the same step as the change itself, and the tiles are made
from the record alone, with no lock. The record is never changed, only replaced, so the versions, the map image's
grid and the model a tile is made from always belong together, and a tile never waits for a job.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from grand_project.webmap.tiles import Grid


def _empty_view() -> dict:
    """The view model of no atlas."""
    return {"nodes": [], "paths": [], "icons": [], "landmarks": [], "final": None}


@dataclasses.dataclass(frozen=True, eq=False)
class TileSource:
    """What the vector tiles and the 3D scene are made from, as it was at one moment (never changed: replaced).

    The model (V, D) and the map image (terrain) it holds are themselves replaced whole by their own changes, never
    changed in place, so holding them here keeps them as they were.
    """

    gen: int = 0  # the open atlas's generation
    V: dict = dataclasses.field(default_factory=_empty_view)  # the view model (session.V)
    D: dict = dataclasses.field(default_factory=dict)  # what is derived from it (session.D)
    flags: dict = dataclasses.field(default_factory=dict)  # the filters (MapImageMixin._flags)
    model_version: int = 0
    filter_version: int = 0
    terrain_version: int = 0
    terrain: tuple | None = None  # (canvas, weight, origin) of the map image, or None
    grid: Grid | None = None  # the map image's grid, or None
    replay: dict | None = None  # the timelapse's step of every item while it is open (replay_steps), else None
    replay_token: int = 0  # bumped with every timelapse plan

    def key(self, steps: bool) -> tuple:
        """The versions the tiles made from it are kept under: model, filters, map image, timelapse plan.

        Args:
            steps: The timelapse's tiles (items carry their reveal step).

        Returns:
            (model_version, filter_version, terrain_version, replay_token or 0).
        """
        return (self.model_version, self.filter_version, self.terrain_version, self.replay_token if steps else 0)

    def with_(self, **changes: Any) -> TileSource:
        """A new record with some of its parts changed (this one stays as it is).

        Args:
            **changes: Field name -> new value.

        Returns:
            The new record.
        """
        return dataclasses.replace(self, **changes)
