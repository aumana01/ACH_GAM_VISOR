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
    "systems": "sistemas.geojson.gz",
    "municipal": "municipalidades.geojson",
    "esph": "esph.geojson",
    "asadas": "asadas.geojson.gz",
    "thiessen": "cobertura-thiessen-asadas.geojson.gz",
    "criteria": "criterios-especiales.geojson",
    "ona": "onas.geojson",
    "protected": "areas-protegidas.geojson",
    "districts": "distritos.geojson.gz",
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
BRAND_LOGO = MAP_DIR / "assets" / "logo-aya-65.jpg"

# Parche de interacción que se ejecuta inmediatamente después de Leaflet y antes
# de app.js. Mantiene una referencia al mapa para poder limpiar objetos temporales
# y hace que las coberturas sean transparentes al clic mientras se coloca un pin.
MAP_INTERACTION_FIX = r"""
(() => {
  "use strict";

  const originalMapFactory = L.map;
  L.map = function (...args) {
    const map = originalMapFactory(...args);
    window.__ACH_GAM_MAP__ = map;
    return map;
  };

  window.setTimeout(() => {
    const map = window.__ACH_GAM_MAP__;
    if (!map) return;

    const pinTool = document.getElementById("pinTool");
    const measureTool = document.getElementById("measureTool");
    const clearLayers = document.getElementById("clearLayers");
    const clearMeasurement = document.getElementById("clearMeasurement");
    const measurementPanel = document.getElementById("measurementPanel");
    const coordinateLatitude = document.getElementById("coordinateLatitude");
    const coordinateLongitude = document.getElementById("coordinateLongitude");
    const mapMessage = document.getElementById("mapMessage");

    const clickThroughPanes = [
      "restrictions",
      "reference",
      "estimatedCoverage",
      "operators",
      "criteria",
      "systems",
      "operatorPoints",
      "drawings",
    ];
    const previousPointerEvents = new Map();

    function setCoordinateClickThrough(enabled) {
      clickThroughPanes.forEach((paneName) => {
        const pane = map.getPane(paneName);
        if (!pane) return;
        if (enabled) {
          if (!previousPointerEvents.has(paneName)) {
            previousPointerEvents.set(paneName, pane.style.pointerEvents || "");
          }
          pane.style.pointerEvents = "none";
        } else if (previousPointerEvents.has(paneName)) {
          pane.style.pointerEvents = previousPointerEvents.get(paneName);
          previousPointerEvents.delete(paneName);
        }
      });
    }

    function syncCoordinateClickThrough() {
      setCoordinateClickThrough(Boolean(pinTool?.classList.contains("active")));
    }

    function disableGeomanModes() {
      map.pm?.disableDraw?.();
      map.pm?.disableGlobalEditMode?.();
      map.pm?.disableGlobalRemovalMode?.();
      map.pm?.disableGlobalDragMode?.();
      map.pm?.disableGlobalRotateMode?.();
      map.pm?.disableGlobalCutMode?.();
    }

    function removeTemporaryMapLayers() {
      disableGeomanModes();

      const geomanLayers = map.pm?.getGeomanDrawLayers?.() || [];
      geomanLayers.forEach((layer) => {
        if (map.hasLayer(layer)) map.removeLayer(layer);
      });

      const temporaryLayers = [];
      map.eachLayer((layer) => {
        const pane = layer?.options?.pane;
        if (pane === "drawings" || pane === "coordinatePins") {
          temporaryLayers.push(layer);
        }
      });
      temporaryLayers.forEach((layer) => {
        if (map.hasLayer(layer)) map.removeLayer(layer);
      });
    }

    pinTool?.addEventListener("click", () => {
      window.setTimeout(syncCoordinateClickThrough, 0);
    });

    measureTool?.addEventListener("click", () => {
      window.setTimeout(() => setCoordinateClickThrough(false), 0);
    });

    map.on("click", () => {
      window.setTimeout(syncCoordinateClickThrough, 0);
    });
    map.on("pm:drawstart", () => setCoordinateClickThrough(false));

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        window.setTimeout(() => setCoordinateClickThrough(false), 0);
      }
    });

    clearLayers?.addEventListener("click", () => {
      setCoordinateClickThrough(false);

      if (pinTool?.classList.contains("active")) pinTool.click();
      if (measureTool?.classList.contains("active") || !measurementPanel?.hidden) {
        clearMeasurement?.click();
      }

      removeTemporaryMapLayers();
      map.closePopup();

      if (coordinateLatitude) coordinateLatitude.value = "";
      if (coordinateLongitude) coordinateLongitude.value = "";

      if (mapMessage) {
        mapMessage.textContent = "Mapa restablecido: se eliminaron dibujos, pines, mediciones e importaciones temporales.";
        mapMessage.classList.remove("error");
        mapMessage.classList.add("visible");
        window.setTimeout(() => mapMessage.classList.remove("visible"), 4200);
      }
    });
  }, 0);
})();
"""


st.set_page_config(
    page_title="Estado Hídrico de los Sistemas AyA · GAM y Periféricos",
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

    paths = [MAP_DIR / "index.html", BRAND_LOGO, *STYLE_FILES, *SCRIPT_FILES]
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


def _asset_data_uri(path: Path) -> str:
    """Convierte una imagen local en una URI autocontenida para el iframe."""

    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{payload}"


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
    html = html.replace(
        'src="assets/logo-aya-65.jpg"',
        f'src="{_asset_data_uri(BRAND_LOGO)}"',
    )

    embedded_data = {}
    embedded_gzip = {}
    for key, filename in DATA_FILES.items():
        path = DATA_DIR / filename
        if path.suffix == ".gz":
            embedded_gzip[key] = base64.b64encode(path.read_bytes()).decode("ascii")
        else:
            embedded_data[key] = json.loads(path.read_text(encoding="utf-8"))
    data_script = json.dumps(
        embedded_data,
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    gzip_script = json.dumps(
        embedded_gzip,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    first_script = '<script src="vendor/leaflet/leaflet.js"></script>'
    html = html.replace(
        first_script,
        f"<script>window.ACH_GAM_DATA={data_script};</script>\n"
        f"<script>window.ACH_GAM_DATA_GZIP={gzip_script};</script>\n"
        f"<script>{_safe_script(SCRIPT_FILES[0].read_text(encoding='utf-8'))}</script>\n"
        f"<script>{_safe_script(MAP_INTERACTION_FIX)}</script>",
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
      html,
      body,
      #root,
      .stApp {
        width: 100%;
        height: 100%;
        margin: 0;
        overflow: hidden !important;
      }

      .stApp > header,
      footer {
        display: none !important;
      }

      [data-testid="stAppViewContainer"],
      [data-testid="stMain"],
      .stMain {
        position: fixed;
        inset: 0;
        width: 100%;
        height: 100vh;
        height: 100dvh;
        overflow: hidden !important;
        background: #f4f8fb;
      }

      [data-testid="stMainBlockContainer"],
      .block-container {
        position: absolute;
        inset: 0;
        width: 100%;
        max-width: none;
        height: 100%;
        min-height: 0;
        padding: 0 !important;
        margin: 0 !important;
        overflow: hidden !important;
      }

      [data-testid="stVerticalBlock"] {
        height: 100%;
        min-height: 0;
        gap: 0 !important;
      }

      /* El autorefresh continúa activo, pero no reserva espacio visual. */
      [data-testid="stElementContainer"]:has(
        iframe[title="streamlit_autorefresh.st_autorefresh"]
      ) {
        position: absolute;
        width: 0;
        height: 0;
        overflow: hidden;
      }

      [data-testid="stElementContainer"]:has(
        iframe[title="streamlit.components.v1.html"]
      ),
      [data-testid="stIFrame"],
      iframe[title="streamlit.components.v1.html"] {
        display: block;
        width: 100% !important;
        height: 100vh !important;
        height: 100dvh !important;
        min-height: 0 !important;
        margin: 0 !important;
        border: 0;
        overflow: hidden !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

try:
    components.html(
        build_map_html(_asset_signature()),
        # Altura de respaldo; el CSS exterior la ajusta al alto real de la
        # ventana para impedir que la página completa tenga desplazamiento.
        height=1000,
        scrolling=False,
    )
except (FileNotFoundError, json.JSONDecodeError, OSError) as error:
    st.error(
        "No fue posible cargar el Visor de Estado Hídrico de los Sistemas AyA. "
        f"Revise los archivos públicos del proyecto: {error}"
    )
