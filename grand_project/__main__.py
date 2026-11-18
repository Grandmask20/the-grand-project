"""python -m grand_project [atlas.json]: starts the app (a local web server) and opens it in the browser."""

from grand_project.app.server import main

if __name__ == "__main__":
    raise SystemExit(main())
