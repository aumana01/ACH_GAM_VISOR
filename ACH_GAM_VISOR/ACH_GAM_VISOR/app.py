"""Punto de entrada compatible con la ruta configurada en Streamlit Cloud."""

from __future__ import annotations

import runpy
from pathlib import Path


ROOT_APP = Path(__file__).resolve().parents[2] / "app.py"

if not ROOT_APP.is_file():
    raise FileNotFoundError(f"No se encontró la aplicación principal: {ROOT_APP}")

runpy.run_path(str(ROOT_APP), run_name="__main__")
