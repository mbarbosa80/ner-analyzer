"""2.12.2 — a white page on two other computers.

The interface is an ES module (``<script type="module">``). Browsers refuse a
module served as anything but a JavaScript type, and Python takes the type from
the Windows registry, where ``.js`` is often ``text/plain``. The server now
fixes the types itself.
"""

from __future__ import annotations

import mimetypes

from fastapi.testclient import TestClient

from app import main


def test_js_is_javascript_even_when_the_registry_says_otherwise():
    mimetypes.add_type("text/plain", ".js")          # what a bad registry does
    import importlib
    importlib.reload(main)
    assert mimetypes.guess_type("x.js")[0] == "text/javascript"
    assert mimetypes.guess_type("x.mjs")[0] == "text/javascript"
    assert mimetypes.guess_type("x.css")[0] == "text/css"


def test_the_bundle_is_served_as_javascript():
    assets = main.STATIC_DIR / "assets"
    js = next(p for p in assets.iterdir() if p.suffix == ".js")
    r = TestClient(main.app).get(f"/assets/{js.name}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/javascript")
