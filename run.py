"""Development entrypoint.

Usage:
    python seed.py        # (once) load demo data
    python run.py         # start the app -> http://127.0.0.1:5000

This is the local development server. Production serves the same `app` object
through Gunicorn instead:

    gunicorn -w 4 -b 0.0.0.0:$PORT "run:app"
"""
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    # Debug reloading is only appropriate for the development config; never
    # hardcode it on, or a misconfigured production start would expose a
    # debugger on the network.
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", 5000)),
        debug=bool(app.config.get("DEBUG")),
    )
