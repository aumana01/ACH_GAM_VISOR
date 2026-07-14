#!/usr/bin/env python3
"""Ejecuta app.py con dobles mínimos para verificar el HTML cartográfico."""

from __future__ import annotations

import runpy
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT_ENTRYPOINT = ROOT / "ACH_GAM_VISOR" / "ACH_GAM_VISOR" / "app.py"
rendered: dict[str, object] = {}


def cache_data(*_args, **_kwargs):
    def decorator(function):
        return function

    return decorator


streamlit = types.ModuleType("streamlit")
streamlit.set_page_config = lambda **_kwargs: None
streamlit.cache_data = cache_data
streamlit.markdown = lambda *_args, **_kwargs: None
streamlit.error = lambda message: rendered.setdefault("error", message)

components_package = types.ModuleType("streamlit.components")
components_v1 = types.ModuleType("streamlit.components.v1")


def render_html(source: str, *, height: int, scrolling: bool) -> None:
    rendered.update(source=source, height=height, scrolling=scrolling)


components_v1.html = render_html
components_package.v1 = components_v1
streamlit.components = components_package

autorefresh = types.ModuleType("streamlit_autorefresh")
autorefresh.st_autorefresh = lambda **_kwargs: 0

sys.modules.update(
    {
        "streamlit": streamlit,
        "streamlit.components": components_package,
        "streamlit.components.v1": components_v1,
        "streamlit_autorefresh": autorefresh,
    }
)

runpy.run_path(str(DEPLOYMENT_ENTRYPOINT), run_name="__main__")

if rendered.get("error"):
    raise RuntimeError(rendered["error"])

app_source = DEPLOYMENT_ENTRYPOINT.parents[2].joinpath("app.py").read_text(
    encoding="utf-8"
)
for token in (
    "height: 100dvh",
    "overflow: hidden !important",
    'iframe[title="streamlit.components.v1.html"]',
):
    if token not in app_source:
        raise RuntimeError(f"La vista fija de Streamlit no contiene: {token}")

html = rendered.get("source")
if not isinstance(html, str) or len(html) < 1_000_000:
    raise RuntimeError("La aplicación no generó el documento cartográfico esperado.")

required_tokens = (
    "window.ACH_GAM_DATA=",
    "Leaflet 1.9.4",
    "drawText: true",
    "ACH GAM VISOR",
    '"condicion":"Déficit"',
    '"condicion":"Superávit"',
    '"alcance":"Cobertura somera/estimada"',
    '"tipo":"Facilidad"',
    '"tipo":"Restricción"',
    "Metodología para el Análisis de Capacidad Hídrica",
    "openCategoryInfo",
    "Conocer esta categoría hídrica",
    "if (target) target.textContent = value",
)
for token in required_tokens:
    if token not in html:
        raise RuntimeError(f"El paquete HTML no contiene: {token}")

local_references = (
    'src="vendor/',
    'href="vendor/',
    'src="app.js"',
    'href="styles.css"',
)
for token in local_references:
    if token in html:
        raise RuntimeError(f"Quedó una referencia local sin empaquetar: {token}")

print(
    {
        "status": "ok",
        "htmlBytes": len(html.encode("utf-8")),
        "height": rendered.get("height"),
        "scrolling": rendered.get("scrolling"),
    }
)
