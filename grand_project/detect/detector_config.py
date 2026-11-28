"""Which detector a process runs: the classical one or the optional RF-DETR model (its model and device), and how
many screenshots are detected at once.

One setting per process, never read from the environment: the app sets it from its saved settings as it starts
(Log > Experimental; a change applies after a restart), the command-line tools from their ``--rf-detr`` flags, and
the detection's worker processes get their parent's through ``fileio.process_pool``'s initializer (spawned workers
start blank).
"""

from __future__ import annotations

import argparse
import importlib.util
from dataclasses import asdict, dataclass

from . import constants as K


@dataclass(frozen=True)
class DetectorConfig:
    """The detector settings.

    Attributes:
        rf_detr: Detect with the RF-DETR model instead of the classical detector.
        model: Its fine-tuned model: a folder or a Hugging Face id ``owner/name[@revision]``; "" is
            ``RF_DETR_DEFAULT_MODEL_DIR``.
        device: One of ``RF_DETR_DEVICES``.
        workers: Screenshots detected at once (worker processes; at most one fewer than the cores).
    """

    rf_detr: bool = False
    model: str = ""
    device: str = "auto"
    workers: int = K.DETECT_WORKERS_DEFAULT

    @classmethod
    def from_dict(cls, d: dict) -> DetectorConfig:
        """The settings a saved or sent dict holds, each brought into range (an unknown device is "auto", a worker
        count below 1 or not a number is 1 / the default); keys it lacks keep their defaults."""
        default = cls()
        device = str(d.get("device", default.device)).strip().lower()
        try:
            workers = max(1, int(d.get("workers", default.workers)))
        except (TypeError, ValueError):
            workers = default.workers
        return cls(
            rf_detr=bool(d.get("rf_detr", default.rf_detr)),
            model=str(d.get("model") or "").strip(),
            device=device if device in K.RF_DETR_DEVICES else default.device,
            workers=workers,
        )

    def to_dict(self) -> dict:
        """As saved and sent to the page."""
        return asdict(self)


_CONFIG = DetectorConfig()


def current() -> DetectorConfig:
    """This process's detector settings."""
    return _CONFIG


def configure(config: DetectorConfig) -> None:
    """Set this process's detector settings (also the detection pool's initializer). A model loaded already stays: it
    refuses to run for another model (``rf_detr_model._load_runtime``) until ``reset_rf_detr_runtime``."""
    global _CONFIG
    _CONFIG = config


def rf_detr_missing() -> str | None:
    """The first package RF-DETR needs that is not installed (``RF_DETR_PACKAGES``), None when all are."""
    return next((name for name in K.RF_DETR_PACKAGES if importlib.util.find_spec(name) is None), None)


def add_arguments(ap: argparse.ArgumentParser) -> None:
    """The command-line flags that choose the detector (``from_args`` reads them, ``cli_args`` writes them)."""
    ap.add_argument("--rf-detr", action="store_true", help="detect with the optional RF-DETR model")
    ap.add_argument(
        "--rf-detr-model",
        default="",
        metavar="MODEL",
        help=f"its folder or Hugging Face id owner/name[@revision] (default {K.RF_DETR_DEFAULT_MODEL_DIR})",
    )
    ap.add_argument("--rf-detr-device", default="auto", choices=K.RF_DETR_DEVICES, help="its torch device")


def from_args(args: argparse.Namespace, workers: int = K.DETECT_WORKERS_DEFAULT) -> DetectorConfig:
    """The settings ``add_arguments``' flags chose."""
    return DetectorConfig(
        rf_detr=args.rf_detr, model=args.rf_detr_model.strip(), device=args.rf_detr_device, workers=workers
    )


def cli_args(config: DetectorConfig) -> list[str]:
    """The flags that choose ``config``'s detector in another command (the builder run by tools.compare_detectors)."""
    if not config.rf_detr:
        return []
    model = config.model or str(K.RF_DETR_DEFAULT_MODEL_DIR)
    return ["--rf-detr", "--rf-detr-model", model, "--rf-detr-device", config.device]


__all__ = [
    "DetectorConfig",
    "add_arguments",
    "cli_args",
    "configure",
    "current",
    "from_args",
    "rf_detr_missing",
]
