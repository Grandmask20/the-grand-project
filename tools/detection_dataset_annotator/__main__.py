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
    """``streamlit run`` with the page and ``args``, listening on ``LOOPBACK`` unless the address is given."""
    given = any(arg == "--server.address" or arg.startswith("--server.address=") for arg in args)
    default = [] if given or os.environ.get("STREAMLIT_SERVER_ADDRESS") else ["--server.address", LOOPBACK]
    return ["streamlit", "run", str(app), *default, *args]  # before the user's: a "--" in them starts the page's


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
