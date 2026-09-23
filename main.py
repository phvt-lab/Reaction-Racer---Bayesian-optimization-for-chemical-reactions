"""Reaction Racer — Bayesian optimization GUI (NiceGUI + Facebook Ax).

Run as web app:      python main.py            (http://localhost:8080)
Desktop window:      python main.py --desktop  (pywebview native window)
Dev auto-reload:     python main.py --reload
"""

import os
import sys

from nicegui import ui

import theme  # noqa: F401  (registers global CSS)
from core import storage
import pages.workspace  # noqa: F401  (registers / and /login)
import pages.dashboard  # noqa: F401  (registers /campaign)
import pages.config  # noqa: F401  (registers /config)
import pages.results  # noqa: F401  (registers /results)
import pages.analysis  # noqa: F401  (registers /analysis)
# Campaign state is loaded per username session when a workspace is opened.


def _flag(name: str) -> bool:
    return name in sys.argv[1:]


if __name__ == '__main__':
    native = _flag('--desktop')
    ui.run(
        title='Reaction Racer',
        favicon='⚗️',
        storage_secret=storage.storage_secret(),
        host='127.0.0.1' if native else '0.0.0.0',
        port=int(os.environ.get('PORT', 8080)),
        dark=True,
        native=native,
        window_size=(1500, 950) if native else None,
        reload=_flag('--reload'),
        show=_flag('--open'),
    )
