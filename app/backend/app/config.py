"""Application settings."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings

from .version import APP_NAME, __version__

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    app_name: str = APP_NAME
    #: Read from the VERSION file at the project root — see ``app/version.py``.
    version: str = __version__

    data_dir: Path = Path(os.environ.get("NER_DATA_DIR", BASE_DIR / "data"))
    # The database lives in the data folder (4.8.0): ``NER_DATA_DIR`` alone
    # used to move the uploads and leave the database where it was.
    database_url: str = os.environ.get(
        "NER_DATABASE_URL",
        f"sqlite:///{Path(os.environ.get('NER_DATA_DIR', BASE_DIR / 'data')) / 'ner.sqlite3'}")

    max_upload_mb: int = int(os.environ.get("NER_MAX_UPLOAD_MB", "200"))
    allowed_pdf_types: tuple[str, ...] = ("application/pdf",)
    allowed_sheet_suffixes: tuple[str, ...] = (".xlsx", ".xlsm", ".csv")

    #: Optimisation time budget per solve, in seconds.
    solver_time_limit_s: float = float(os.environ.get("NER_SOLVER_SECONDS", "25"))

    #: Hard ceiling on the placement model. The solver's own time limit does not
    #: cover building the model, so without this an oversized import pegs a core
    #: for minutes with no feedback.
    max_assignment_vars: int = int(os.environ.get("NER_MAX_MODEL_VARS", "250000"))

    disclaimer: str = (
        "This tool supports the design process. It does not replace engineering "
        "approval, a site survey, cable route validation or physical inspection."
    )

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def composite_dir(self) -> Path:
        """The composite maps (5.0.0): pictures and tiles derived from the
        books, rebuilt on demand — not in a backup, not in a project package."""
        return self.data_dir / "composite"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.uploads_dir, self.exports_dir, self.composite_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
