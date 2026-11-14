"""python -m grand_project.detect score | train | train_fortress | run IMG... | show IMG..."""

import sys

from grand_project.detect import __doc__ as DOC
from grand_project.detect.annotate import cmd_show
from grand_project.detect.pipeline import cmd_run
from grand_project.detect.training import cmd_score, cmd_train
from grand_project.detect.walls import cmd_train_fortress

if __name__ == "__main__":
    cmds = {
        "score": cmd_score,
        "train": cmd_train,
        "train_fortress": cmd_train_fortress,
        "run": cmd_run,
        "show": cmd_show,
    }
    if sys.argv[1:2] and sys.argv[1] in cmds:
        raise SystemExit(cmds[sys.argv[1]]())
    print(DOC)
