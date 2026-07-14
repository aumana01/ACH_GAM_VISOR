#!/usr/bin/env python3
"""Valida estructura, privacidad y coherencia de los datos públicos."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "map" / "data"

SCHEMAS = {
    "sistemas.geojson": {"codigo", "nombre", "condicion", "ich"},
    "municipalidades.geojson": {"operador", "sistema"},
    "esph.geojson": {"operador", "sistema"},
    "asadas.geojson": {"codigo", "operador"},
    "cobertura-thiessen-asadas.geojson": {
        "codigo",
        "referencia",
        "provincia",
        "canton",
        "distrito",
        "alcance",
        "metodo",
    },
    "criterios-especiales.geojson": {
        "codigo_sistema",
        "nombre_sistema",
        "codigo_abastecimiento",
        "zona",
        "zona_operativa",
        "tipo",
        "detalle",
    },
    "onas.geojson": {"operador", "sistema"},
    "areas-protegidas.geojson": {"codigo", "nombre", "categoria"},
    "distritos.geojson": {"provincia", "canton", "distrito"},
}

FORBIDDEN_KEY = re.compile(
    r"correo|tel[eé]fono|globalid|objectid|created_|edited_|servicios|balance|fuente",
    re.IGNORECASE,
)
FAILURES: list[str] = []


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        FAILURES.append(f"{path.name}: no se puede leer ({error}).")
        return {}


def visit_coordinates(value: Any, filename: str) -> None:
    if not isinstance(value, list):
        return
    if (
        len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    ):
        longitude, latitude = value[:2]
        if not (-86.5 <= longitude <= -82 and 8 <= latitude <= 11.5):
            FAILURES.append(
                f"{filename}: coordenada fuera de Costa Rica ({longitude}, {latitude})."
            )
        return
    for child in value:
        visit_coordinates(child, filename)


collections: dict[str, dict[str, Any]] = {}
for filename, allowed_keys in SCHEMAS.items():
    path = DATA_DIR / filename
    if not path.exists():
        FAILURES.append(f"{filename}: archivo faltante.")
        continue
    size_limit = 30_000_000 if filename == "cobertura-thiessen-asadas.geojson" else 5_000_000
    if path.stat().st_size > size_limit:
        FAILURES.append(
            f"{filename}: supera el límite público de {size_limit // 1_000_000} MB."
        )
    collection = load_json(path)
    collections[filename] = collection
    if collection.get("type") != "FeatureCollection" or not isinstance(
        collection.get("features"), list
    ):
        FAILURES.append(f"{filename}: no es una FeatureCollection GeoJSON válida.")
        continue
    for feature in collection["features"]:
        if not feature.get("geometry"):
            FAILURES.append(f"{filename}: contiene una geometría nula.")
            continue
        properties = feature.get("properties") or {}
        keys = set(properties)
        extra = sorted(keys - allowed_keys)
        if extra:
            FAILURES.append(
                f"{filename}: atributos no autorizados: {', '.join(extra)}."
            )
        sensitive = sorted(key for key in keys if FORBIDDEN_KEY.search(key))
        if sensitive:
            FAILURES.append(
                f"{filename}: atributos sensibles: {', '.join(sensitive)}."
            )
        visit_coordinates(feature["geometry"].get("coordinates"), filename)


systems = collections.get("sistemas.geojson", {}).get("features", [])
unique_systems: dict[str, dict[str, Any]] = {}
for feature in systems:
    properties = feature.get("properties") or {}
    code = properties.get("codigo")
    name = properties.get("nombre")
    condition = properties.get("condicion")
    ich = properties.get("ich")
    if code:
        unique_systems[code] = properties
    if not code or not name:
        FAILURES.append("sistemas.geojson: hay un sistema sin código o nombre.")
    if condition not in {"Déficit", "Superávit"}:
        FAILURES.append(f"{code or 'Sin código'}: condición pública inválida.")
    if ich not in {"I", "II", "III", "IV"}:
        FAILURES.append(f"{code or 'Sin código'}: clasificación ICH inválida.")

metadata = load_json(DATA_DIR / "metadata.json")
deficit = sum(
    item.get("condicion") == "Déficit" for item in unique_systems.values()
)
surplus = sum(
    item.get("condicion") == "Superávit" for item in unique_systems.values()
)
if (
    metadata.get("systems") != len(unique_systems)
    or metadata.get("deficit") != deficit
    or metadata.get("surplus") != surplus
):
    FAILURES.append("metadata.json no coincide con los sistemas publicados.")

app_source = (ROOT / "app.py").read_text(encoding="utf-8")
required_app_tokens = (
    "from streamlit_autorefresh import st_autorefresh",
    "st_autorefresh(",
    "components.html(",
    "logo-aya-65.jpg",
    "Visor de Estado Hídrico del Gran Área Metropolitana",
)
for token in required_app_tokens:
    if token not in app_source:
        FAILURES.append(f"app.py: falta la integración requerida: {token}")

index_source = (ROOT / "map" / "index.html").read_text(encoding="utf-8")
if "Visor de Estado Hídrico del Gran Área Metropolitana" not in index_source:
    FAILURES.append("map/index.html: falta el título oficial del visor")
if "Información pública" in index_source:
    FAILURES.append("map/index.html: todavía muestra el texto Información pública")
if not (ROOT / "map" / "assets" / "logo-aya-65.jpg").exists():
    FAILURES.append("map/assets: falta el logo institucional")

map_source = (ROOT / "map" / "app.js").read_text(encoding="utf-8")
required_map_tokens = (
    "drawText: true",
    "parseKmlOrKmz",
    "captureMap",
    "startCoordinateMode",
    "locateCoordinate",
    "coordinateSearchForm",
    "map.flyTo(latlng, 17",
    "coordinate-highlight",
    "startMeasurement",
    "criteriaPopup",
    "data.thiessen",
    "criteria-dominant",
    "criteria-facility-pattern",
    "criteria-restriction-pattern",
    "criteria-mixed-pattern",
    "closeButton: true",
)
for token in required_map_tokens:
    if token not in map_source:
        FAILURES.append(f"map/app.js: falta la herramienta requerida: {token}")

if "layer.openPopup(event.latlng)" in map_source:
    FAILURES.append("map/app.js: el popup de criterios todavía se abre al pasar el mouse")

styles_source = (ROOT / "map" / "styles.css").read_text(encoding="utf-8")
if ".criteria-dominant:hover" in styles_source:
    FAILURES.append("map/styles.css: criterios especiales todavía cambia al pasar el mouse")

criteria_features = collections.get("criterios-especiales.geojson", {}).get(
    "features", []
)
valid_criteria_types = {"Restricción", "Facilidad", "Criterio especial"}
for feature in criteria_features:
    condition_type = (feature.get("properties") or {}).get("tipo")
    if condition_type not in valid_criteria_types:
        FAILURES.append(
            "criterios-especiales.geojson: tipo de condición pública inválido."
        )

thiessen_features = collections.get(
    "cobertura-thiessen-asadas.geojson", {}
).get("features", [])
for feature in thiessen_features:
    properties = feature.get("properties") or {}
    if properties.get("alcance") != "Cobertura somera/estimada":
        FAILURES.append(
            "cobertura-thiessen-asadas.geojson: debe advertir su alcance estimado."
        )
    if properties.get("metodo") != "Polígono de Thiessen":
        FAILURES.append(
            "cobertura-thiessen-asadas.geojson: método público inválido."
        )

if FAILURES:
    print("\n".join(f"- {failure}" for failure in FAILURES), file=sys.stderr)
    raise SystemExit(1)

print(
    json.dumps(
        {
            "status": "ok",
            "systems": len(unique_systems),
            "deficit": deficit,
            "surplus": surplus,
            "publicLayers": len(SCHEMAS),
        },
        ensure_ascii=False,
        indent=2,
    )
)
