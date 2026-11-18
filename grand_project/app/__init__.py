"""app: the atlas app. A local web server (app.server) holds the open atlas (app.session) and serves the page built
from frontend/ (React, MapLibre); the page talks to it through a JSON API and an event stream.

    python -m grand_project [atlas.json]
"""
