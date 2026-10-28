"""Report which runtime dependencies are present, and which are missing.

Run before starting the server after an upgrade: a missing package should be a
named line here rather than a traceback three seconds into a request.
"""
import importlib
import sys

REQUIRED = [
    ("fastapi", "fastapi"), ("uvicorn", "uvicorn[standard]"),
    ("multipart", "python-multipart"), ("sqlalchemy", "SQLAlchemy"),
    ("pydantic", "pydantic"), ("pydantic_settings", "pydantic-settings"),
    ("pymupdf", "pymupdf"), ("openpyxl", "openpyxl"), ("xlrd", "xlrd"),
    ("pandas", "pandas"), ("shapely", "shapely"), ("networkx", "networkx"),
    ("rapidfuzz", "rapidfuzz"), ("ortools", "ortools"),
    ("pytest", "pytest"), ("httpx", "httpx"),
]

missing = []
for module, package in REQUIRED:
    try:
        importlib.import_module(module)
    except Exception as exc:
        missing.append((module, package, type(exc).__name__))

print("python", sys.version.split()[0])
for module, package, err in missing:
    print(f"MISSING {package} (import {module}: {err})")
print(f"RESULT {len(REQUIRED) - len(missing)}/{len(REQUIRED)} present")
if missing:
    print("PIP_INSTALL " + " ".join(p for _m, p, _e in missing))
