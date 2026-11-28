"""Start the annotator's Streamlit page: ``python -m tools.detection_dataset_annotator [streamlit options]``.

Extra arguments go to ``streamlit run`` (for example ``--server.port 8600`` or ``--server.headless true``). The page
listens on this computer only unless ``--server.address`` (or ``STREAMLIT_SERVER_ADDRESS``) says otherwise: it shows
any screenshot below the roots typed into it.
"""

import os
import sys
from pathlib import Path

LOOPBACK = "127.0.0.1"


def streamlit_args(app: Path, args: list[str]) -> list[str]:
    """``streamlit run`` with the page and ``args``, listening on ``LOOPBACK`` unless an address is given (among
    Streamlit's own options: what follows a ``--`` is the page's).

    A blank address (``--server.address ""``, ``--server.address=``, a blank ``STREAMLIT_SERVER_ADDRESS``) is no address
    given: it is taken out of the options (Streamlit would read it as "every interface") and the default stands.
    """
    split = args.index("--") if "--" in args else len(args)
    own, rest = list(args[:split]), args[split:]
    given = False
    kept: list[str] = []
    skip = False
    for position, arg in enumerate(own):
        if skip:
            skip = False
            continue
        if arg == "--server.address":
            value = own[position + 1] if position + 1 < len(own) else ""
            skip = position + 1 < len(own)  # its value goes with it
        elif arg.startswith("--server.address="):
            value = arg.partition("=")[2]
        else:
            kept.append(arg)
            continue
        if value.strip():
            given = True
            kept += [arg, value] if arg == "--server.address" else [arg]
    default = [] if given or os.environ.get("STREAMLIT_SERVER_ADDRESS", "").strip() else ["--server.address", LOOPBACK]
    return ["streamlit", "run", str(app), *default, *kept, *rest]  # before the user's: a "--" in them starts the page's


def main() -> None:
    """Run ``streamlit run app.py`` in this process, so the project folder stays on the import path."""
    try:
        from streamlit.web import cli
    except ImportError:
        sys.exit('Streamlit is not installed: run `make install_annotator` (pip install -e ".[annotator]").')
    sys.argv = streamlit_args(Path(__file__).resolve().with_name("app.py"), sys.argv[1:])
    sys.exit(cli.main())


if __name__ == "__main__":
    main()
