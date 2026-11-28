"""python -m grand_project.detect score | score_rf_detr | train | train_cities | train_fortress | run IMG... |
show IMG...   [--rf-detr] [--rf-detr-model MODEL] [--rf-detr-device DEVICE] (run / show: the detector; score_rf_detr:
the model)"""

import argparse
import sys

from grand_project.detect import detector_config
from grand_project.detect.rf_detr_cuda import prefer_pip_cuda_libraries

if __name__ == "__main__":
    # the detector flags, taken out of the command line the commands read (their own arguments stay as they were)
    _flags = argparse.ArgumentParser(add_help=False)
    detector_config.add_arguments(_flags)
    _chosen, sys.argv[1:] = _flags.parse_known_args(sys.argv[1:])
    if sys.argv[1:2] == ["score_rf_detr"]:
        _chosen.rf_detr = True
    detector_config.configure(detector_config.from_args(_chosen))
    if _chosen.rf_detr:
        prefer_pip_cuda_libraries()  # before torch loads: RF-DETR on CUDA needs PyTorch's own cuDNN (rf_detr_cuda)

from grand_project.detect import __doc__ as DOC  # noqa: E402
from grand_project.detect.annotate import cmd_show  # noqa: E402
from grand_project.detect.citytrain import cmd_train_cities  # noqa: E402
from grand_project.detect.pipeline import cmd_run  # noqa: E402
from grand_project.detect.training import cmd_score, cmd_score_rf_detr, cmd_train  # noqa: E402
from grand_project.detect.walls import cmd_train_fortress  # noqa: E402

if __name__ == "__main__":
    cmds = {
        "score": cmd_score,
        "score_rf_detr": cmd_score_rf_detr,
        "train": cmd_train,
        "train_cities": cmd_train_cities,
        "train_fortress": cmd_train_fortress,
        "run": cmd_run,
        "show": cmd_show,
    }
    if sys.argv[1:2] and sys.argv[1] in cmds:
        raise SystemExit(cmds[sys.argv[1]]())
    print(DOC)
