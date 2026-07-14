"""Aplicación pública ACH GAM VISOR construida con Streamlit."""

from __future__ import annotations

import base64
import json
import mimetypes
import re
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh


ROOT = Path(__file__).resolve().parent
MAP_DIR = ROOT / "map"
DATA_DIR = MAP_DIR / "data"

DATA_FILES = {
    "metadata": "metadata.json",
    "systems": "sistemas.geojson",
    "municipal": "municipalidades.geojson",
    "esph": "esph.geojson",
    "asadas": "asadas.geojson",
    "ona": "onas.geojson",
    "protected": "areas-protegidas.geojson",
    "districts": "distritos.geojson",
}

STYLE_FILES = (
    MAP_DIR / "vendor" / "leaflet" / "leaflet.css",
    MAP_DIR / "vendor" / "geoman" / "leaflet-geoman.css",
    MAP_DIR / "styles.css",
)

SCRIPT_FILES = (
    MAP_DIR / "vendor" / "leaflet" / "leaflet.js",
    MAP_DIR / "vendor" / "geoman" / "leaflet-geoman.min.js",
    MAP_DIR / "vendor" / "jszip" / "jszip.min.js",
    MAP_DIR / "vendor" / "togeojson" / "togeojson.umd.js",
    MAP_DIR / "vendor" / "screenshoter" / "leaflet-simple-map-screenshoter.js",
    MAP_DIR / "app.js",
)


st.set_page_config(
    page_title="ACH GAM VISOR",
    page_icon="💧",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Recarga el navegador cada 15 minutos. En Streamlit Community Cloud, una nueva
# versión del repositorio dispara además un redespliegue de la aplicación.
st_autorefresh(
    interval=15 * 60 * 1000,
    limit=None,
    key="ach_gam_visor_autorefresh",
)


def _asset_signature() -> tuple[tuple[str, int, int], ...]:
    """Firma liviana que invalida el caché cuando se sustituye un archivo."""

    paths = [MAP_DIR / "index.html", *STYLE_FILES, *SCRIPT_FILES]
    paths.extend(DATA_DIR / filename for filename in DATA_FILES.values())
    result = []
    for path in paths:
        stat = path.stat()
        result.append((str(path.relative_to(ROOT)), stat.st_mtime_ns, stat.st_size))
    return tuple(result)


def _inline_leaflet_images(css: str) -> str:
    """Convierte los iconos de Leaflet en data URI para el iframe de Streamlit."""

    image_dir = MAP_DIR / "vendor" / "leaflet"
    pattern = re.compile(r"url\((['\"]?)(images/[^)'\"]+)\1\)")

    def replace(match: re.Match[str]) -> str:
        relative_path = match.group(2)
        image_path = image_dir / relative_path
        mime_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
        payload = base64.b64encode(image_path.read_bytes()).decode("ascii")
        return f'url("data:{mime_type};base64,{payload}")'

    return pattern.sub(replace, css)


def _safe_script(source: str) -> str:
    """Evita que una secuencia literal cierre prematuramente el script HTML."""

    return source.replace("</script", "<\\/script")


@st.cache_data(show_spinner=False)
def build_map_html(signature: tuple[tuple[str, int, int], ...]) -> str:
    """Empaqueta el visor y los GeoJSON en un único documento autocontenido."""

    # La firma es parte de la llave del caché aunque el contenido no se use aquí.
    _ = signature
    html = (MAP_DIR / "index.html").read_text(encoding="utf-8")

    leaflet_css = _inline_leaflet_images(STYLE_FILES[0].read_text(encoding="utf-8"))
    geoman_css = STYLE_FILES[1].read_text(encoding="utf-8")
    application_css = STYLE_FILES[2].read_text(encoding="utf-8")

    html = html.replace(
        '<link rel="stylesheet" href="vendor/leaflet/leaflet.css">',
        f"<style>{leaflet_css}</style>",
    )
    html = html.replace(
        '<link rel="stylesheet" href="vendor/geoman/leaflet-geoman.css">',
        f"<style>{geoman_css}</style>",
    )
    html = html.replace(
        '<link rel="stylesheet" href="styles.css">',
        f"<style>{application_css}</style>",
    )
    html = html.replace(
        '<link rel="icon" href="assets/favicon.svg" type="image/svg+xml">',
        "",
    )

    embedded_data = {
        key: json.loads((DATA_DIR / filename).read_text(encoding="utf-8"))
        for key, filename in DATA_FILES.items()
    }
    data_script = json.dumps(
        embedded_data,
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    first_script = '<script src="vendor/leaflet/leaflet.js"></script>'
    html = html.replace(
        first_script,
        f"<script>window.ACH_GAM_DATA={data_script};</script>\n"
        f"<script>{_safe_script(SCRIPT_FILES[0].read_text(encoding='utf-8'))}</script>",
    )

    replacements = (
        ("vendor/geoman/leaflet-geoman.min.js", SCRIPT_FILES[1]),
        ("vendor/jszip/jszip.min.js", SCRIPT_FILES[2]),
        ("vendor/togeojson/togeojson.umd.js", SCRIPT_FILES[3]),
        ("vendor/screenshoter/leaflet-simple-map-screenshoter.js", SCRIPT_FILES[4]),
        ("app.js", SCRIPT_FILES[5]),
    )
    for source_name, source_path in replacements:
        html = html.replace(
            f'<script src="{source_name}"></script>',
            f"<script>{_safe_script(source_path.read_text(encoding='utf-8'))}</script>",
        )
    return html


st.markdown(
    """
    <style>
      .stApp > header { display: none; }
      .block-container { max-width: 100%; padding: 0; }
      [data-testid="stAppViewContainer"] { background: #f4f8fb; }
      [data-testid="stIFrame"] { display: block; }
      iframe { display: block; border: 0; }
    </style>
    """,
    unsafe_allow_html=True,
)

try:
    components.html(
        build_map_html(_asset_signature()),
        height=920,
        scrolling=False,
    )
except (FileNotFoundError, json.JSONDecodeError, OSError) as error:
    st.error(
        "No fue posible cargar ACH GAM VISOR. "
        f"Revise los archivos públicos del proyecto: {error}"
    )

