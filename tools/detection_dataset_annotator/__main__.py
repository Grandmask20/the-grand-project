"""Start the annotator's Streamlit page: ``python -m tools.detection_dataset_annotator [streamlit options]``.

Extra arguments go to ``streamlit run`` (for example ``--server.port 8600`` or ``--server.headless true``).
"""

import sys
from pathlib import Path


def main() -> None:
    """Run ``streamlit run app.py`` in this process, so the project folder stays on the import path."""
    try:
        from streamlit.web import cli
    except ImportError:
        sys.exit('Streamlit is not installed: run `make install_annotator` (pip install -e ".[annotator]").')
    app = Path(__file__).resolve().with_name("app.py")
    sys.argv = ["streamlit", "run", str(app), *sys.argv[1:]]
    sys.exit(cli.main())


if __name__ == "__main__":
    main()
