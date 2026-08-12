#!/usr/bin/env python3
"""Valida estructura, privacidad y coherencia de los datos públicos."""

from __future__ import annotations

import json
import gzip
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "map" / "data"

SCHEMAS = {
    "sistemas.geojson.gz": {
        "codigo",
        "region",
        "nombre",
        "ich",
        "dotacion_lpd",
        "consumo_conexion_m3_mes",
        "factor_ocupacion",
        "territorios",
    },
    "municipalidades.geojson": {"operador", "sistema"},
    "esph.geojson": {"operador", "sistema"},
    "asadas.geojson.gz": {"codigo", "nombre", "territorio"},
    "cobertura-thiessen-asadas.geojson.gz": {
        "codigo",
        "referencia",
        "provincia",
        "canton",
        "distrito",
        "alcance",
        "metodo",
        "territorios",
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
    "distritos.geojson.gz": {
        "clave",
        "codigo",
        "provincia",
        "canton",
        "distrito",
    },
}

FORBIDDEN_KEY = re.compile(
    r"correo|tel[eé]fono|globalid|objectid|created_|edited_|servicios|balance|fuente|producci[oó]n|demanda|(?:^|_)anc(?:_|$)|equivalencia",
    re.IGNORECASE,
)
FAILURES: list[str] = []


def load_json(path: Path) -> dict[str, Any]:
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8-sig") as source:
                return json.load(source)
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, EOFError, json.JSONDecodeError) as error:
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
        if not (-87.2 <= longitude <= -82 and 5.4 <= latitude <= 11.5):
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
    size_limit = 30_000_000 if filename in {
        "cobertura-thiessen-asadas.geojson.gz",
        "sistemas.geojson.gz",
        "distritos.geojson.gz",
    } else 15_000_000
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


systems = collections.get("sistemas.geojson.gz", {}).get("features", [])
unique_systems: dict[str, dict[str, Any]] = {}
valid_regions = {
    "Brunca",
    "Central Oeste",
    "Chorotega",
    "Huetar Caribe",
    "Metropolitana",
    "Pacífico Central",
}
for feature in systems:
    properties = feature.get("properties") or {}
    code = properties.get("codigo")
    name = properties.get("nombre")
    region = properties.get("region")
    ich = properties.get("ich")
    if code:
        unique_systems[code] = properties
    if not code or not name:
        FAILURES.append("sistemas.geojson.gz: hay un sistema sin código o nombre.")
    if not re.fullmatch(r"(?:BR|CH|CO|HC|ME|PC)A\d{2}", str(code or "")):
        FAILURES.append(f"{code or 'Sin código'}: código público inválido.")
    if region not in valid_regions:
        FAILURES.append(f"{code or 'Sin código'}: región operativa inválida.")
    if ich not in {"I", "II", "III", "IV", "SIN DATOS"}:
        FAILURES.append(f"{code or 'Sin código'}: clasificación ICH inválida.")
    for field in ("dotacion_lpd", "consumo_conexion_m3_mes"):
        if not isinstance(properties.get(field), (int, float)):
            FAILURES.append(f"{code or 'Sin código'}: {field} debe ser numérico.")
    factor = properties.get("factor_ocupacion")
    if factor is not None and not isinstance(factor, (int, float)):
        FAILURES.append(f"{code or 'Sin código'}: factor_ocupacion inválido.")

district_features = collections.get("distritos.geojson.gz", {}).get("features", [])
district_keys: set[str] = set()
for feature in district_features:
    properties = feature.get("properties") or {}
    key = str(properties.get("clave") or "").strip()
    if not key:
        FAILURES.append("distritos.geojson.gz: falta la clave territorial.")
    elif key in district_keys:
        FAILURES.append(f"distritos.geojson.gz: clave duplicada {key}.")
    district_keys.add(key)
    for field in ("provincia", "canton", "distrito"):
        value = str(properties.get(field) or "").strip()
        if not value:
            FAILURES.append(f"distritos.geojson.gz: falta el nombre de {field}.")
        elif value.isdigit():
            FAILURES.append(
                f"distritos.geojson.gz: {field} debe mostrar un nombre, no el código {value}."
            )

if len({f["properties"]["provincia"] for f in district_features}) != 7:
    FAILURES.append("distritos.geojson.gz: la cobertura debe contener 7 provincias.")

for feature in systems:
    properties = feature.get("properties") or {}
    territories = properties.get("territorios")
    if not isinstance(territories, list) or not territories:
        FAILURES.append(
            f"{properties.get('codigo') or 'Sin código'}: falta relación territorial."
        )
    elif not set(territories).issubset(district_keys):
        FAILURES.append(
            f"{properties.get('codigo') or 'Sin código'}: contiene claves territoriales inválidas."
        )

asada_features = collections.get("asadas.geojson.gz", {}).get("features", [])
for feature in asada_features:
    properties = feature.get("properties") or {}
    if not str(properties.get("nombre") or "").strip():
        FAILURES.append("asadas.geojson.gz: hay un punto sin nombre de ASADA.")
    if properties.get("territorio") not in district_keys:
        FAILURES.append("asadas.geojson.gz: hay un punto sin relación territorial válida.")

metadata = load_json(DATA_DIR / "metadata.json")
regions = {item.get("region") for item in unique_systems.values()}
category_counts = {
    category: sum(item.get("ich") == category for item in unique_systems.values())
    for category in ("I", "II", "III", "IV", "SIN DATOS")
}
if (
    metadata.get("systems") != len(unique_systems)
    or metadata.get("regions") != len(regions)
    or metadata.get("categoryCounts") != category_counts
):
    FAILURES.append("metadata.json no coincide con los sistemas publicados.")

expected_feature_counts = {
    "systems": len(systems),
    "asadas": len(asada_features),
    "cobertura-thiessen-asadas": len(
        collections.get("cobertura-thiessen-asadas.geojson.gz", {}).get(
            "features", []
        )
    ),
    "districts": len(district_features),
}
published_feature_counts = metadata.get("featureCounts") or {}
for layer_name, expected in expected_feature_counts.items():
    if published_feature_counts.get(layer_name) != expected:
        FAILURES.append(
            f"metadata.json: conteo inválido para {layer_name}."
        )

app_source = (ROOT / "app.py").read_text(encoding="utf-8")
required_app_tokens = (
    "from streamlit_autorefresh import st_autorefresh",
    "st_autorefresh(",
    "components.html(",
    "logo-aya-65.jpg",
    "Estado Hídrico de los Sistemas AyA · GAM y Periféricos",
    '"systems": "sistemas.geojson.gz"',
    '"asadas": "asadas.geojson.gz"',
    '"districts": "distritos.geojson.gz"',
    "window.ACH_GAM_DATA_GZIP",
    'height: 100dvh',
    'overflow: hidden !important',
    'iframe[title="streamlit.components.v1.html"]',
)
for token in required_app_tokens:
    if token not in app_source:
        FAILURES.append(f"app.py: falta la integración requerida: {token}")

index_source = (ROOT / "map" / "index.html").read_text(encoding="utf-8")
if "Visor de Estado Hídrico de los Sistemas AyA" not in index_source:
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
    "thiessenData",
    "criteria-dominant",
    "criteria-facility-pattern",
    "criteria-restriction-pattern",
    "criteria-mixed-pattern",
    "closeButton: true",
    "CATEGORY_INFO",
    "openCategoryInfo",
    "popup-category-info",
    "metadataLabels",
    "if (target) target.textContent = value",
    "regionFilter",
    "systemFilter",
    "categoryFilter",
    "provinceFilter",
    "cantonFilter",
    "districtFilter",
    "matchesSelectedTerritory",
    "refreshTerritorialLayers",
    "decompressGzipJson",
    "layerFactories.municipal",
    "layerFactories.ona",
    "Organización de usuarios de agua",
    "Distrito de Costa Rica",
)
for token in required_map_tokens:
    if token not in map_source:
        FAILURES.append(f"map/app.js: falta la herramienta requerida: {token}")

if "layer.openPopup(event.latlng)" in map_source:
    FAILURES.append("map/app.js: el popup de criterios todavía se abre al pasar el mouse")

unsafe_text_targets = re.findall(
    r'document\.getElementById\("([^"]+)"\)\.textContent',
    map_source,
)
if unsafe_text_targets:
    FAILURES.append(
        "map/app.js: hay actualizaciones de texto sin validar el elemento: "
        + ", ".join(sorted(set(unsafe_text_targets)))
    )

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
    "cobertura-thiessen-asadas.geojson.gz", {}
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
    territories = properties.get("territorios")
    if not isinstance(territories, list) or not territories:
        FAILURES.append(
            "cobertura-thiessen-asadas.geojson.gz: falta relación territorial."
        )
    elif not set(territories).issubset(district_keys):
        FAILURES.append(
            "cobertura-thiessen-asadas.geojson.gz: contiene claves territoriales inválidas."
        )

if FAILURES:
    print("\n".join(f"- {failure}" for failure in FAILURES), file=sys.stderr)
    raise SystemExit(1)

print(
    json.dumps(
        {
            "status": "ok",
            "systems": len(unique_systems),
            "regions": len(regions),
            "categories": category_counts,
            "asadaPoints": len(asada_features),
            "districts": len(district_features),
            "publicLayers": len(SCHEMAS),
        },
        ensure_ascii=False,
        indent=2,
    )
)
