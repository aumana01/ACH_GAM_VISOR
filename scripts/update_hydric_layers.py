#!/usr/bin/env python3
"""Actualiza capacidad GAM y criterios desde los ZIP públicos de Shapefile.

Los indicadores no presentes en el SHP se toman de metricas_gam_2026.csv.
MEA23 se integró en MEA16 y se retira de la capa pública.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from import_national_territorial_layers import district_index, matching_district_indices, safe_geometry
from import_shapefile_layers import (
    _dbf_encoding,
    clean,
    normalize_code,
    normalized_text,
    public_code,
    read_bundle,
    read_dbf,
    read_shp,
    coordinate_transform,
    special_condition,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "map" / "data"
DEFAULT_METRICS = Path(__file__).resolve().with_name("metricas_gam_2026.csv")
FORMER_MEA23_GEOMETRY = Path(__file__).resolve().with_name("area_mea23_barrio_espana.geojson")
MERGED_SYSTEMS = {"MEA23": "MEA16"}


def read_metrics(path: Path):
    metrics = {}
    with path.open(newline="", encoding="utf-8-sig") as source:
        for row in csv.DictReader(source):
            code = normalize_code(row["codigo"])
            if not code or code in metrics or code in MERGED_SYSTEMS:
                raise ValueError(f"Código duplicado o inválido en indicadores: {code}")
            values = {
                field: float(row[field])
                for field in ("factor_ocupacion", "consumo_conexion_m3_mes", "dotacion_lpd")
            }
            if any(not math.isfinite(value) or value <= 0 for value in values.values()):
                raise ValueError(f"Indicadores inválidos para {code}")
            metrics[code] = values
    return metrics


def load_shapefile(path: Path):
    bundle = read_bundle(path)
    rows = read_dbf(bundle.dbf, _dbf_encoding(bundle.cpg))
    geometries = read_shp(bundle.shp, coordinate_transform(bundle.prj))
    if len(rows) != len(geometries):
        raise ValueError(f"{path.name}: SHP y DBF no coinciden")
    return [(row, geometry) for row, geometry in zip(rows, geometries) if row and geometry]


def zone_key(code: str, name: str):
    return normalize_code(code), normalized_text(name).casefold().strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capacity", type=Path, required=True)
    parser.add_argument("--criteria", type=Path, required=True)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args()
    data_dir = args.data_dir

    with gzip.open(data_dir / "sistemas.geojson.gz", "rt", encoding="utf-8") as source:
        old_systems = json.load(source)
    with gzip.open(data_dir / "distritos.geojson.gz", "rt", encoding="utf-8") as source:
        districts = json.load(source)
    old_by_code = {feature["properties"]["codigo"]: feature["properties"] for feature in old_systems["features"]}
    metrics = read_metrics(args.metrics)
    district_geometries, district_tree = district_index(districts)

    capacity_rows = load_shapefile(args.capacity)
    if not capacity_rows:
        raise ValueError("La capa de capacidad está vacía")
    categories = defaultdict(set)
    zones = defaultdict(list)
    new_features = []
    for row, geometry in capacity_rows:
        code = normalize_code(row.get("Codigo_Sis"))
        if code not in old_by_code:
            raise ValueError(f"Falta la ficha pública previa del sistema {code}")
        ich = clean(row.get("ICH")).upper()
        if ich not in {"I", "II", "III", "IV", "SIN DATOS"}:
            raise ValueError(f"ICH no válido para {code}: {ich}")
        categories[code].add(ich)
        keys = sorted({districts["features"][i]["properties"]["clave"]
                       for i in matching_district_indices(safe_geometry(geometry), district_geometries, district_tree)})
        if not keys:
            raise ValueError(f"Sin distrito para {code}, {row.get('zonas')}")
        properties = {**old_by_code[code], **metrics.get(code, {}), "ich": ich, "territorios": keys}
        new_features.append({"type": "Feature", "geometry": geometry, "properties": properties})
        zones[zone_key(code, row.get("zonas", ""))].append((row, shape(geometry)))
    inconsistent = {code: values for code, values in categories.items() if len(values) != 1}
    if inconsistent:
        raise ValueError(f"Categorías divergentes dentro del sistema: {inconsistent}")
    if set(categories) != set(metrics):
        raise ValueError(
            f"La tabla de indicadores no coincide con el SHP: "
            f"sin indicadores {sorted(set(categories) - set(metrics))}; "
            f"sin geometría {sorted(set(metrics) - set(categories))}"
        )
    if set(categories) & MERGED_SYSTEMS.keys():
        raise ValueError("El SHP aún incluye un sistema que ya fue unificado")

    # El SHP reciente de MEA16 no contiene toda la antigua área de Barrio España.
    # Se suma únicamente la porción aún descubierta para no duplicar geometrías.
    former_area = safe_geometry(json.loads(FORMER_MEA23_GEOMETRY.read_text(encoding="utf-8")))
    current_mea16 = unary_union([
        safe_geometry(feature["geometry"]) for feature in new_features
        if feature["properties"]["codigo"] == "MEA16"
    ])
    if current_mea16.is_empty:
        raise ValueError("La fuente nueva no contiene MEA16")
    supplemental_area = former_area.difference(current_mea16)
    if not supplemental_area.is_empty:
        supplemental_geometry = mapping(supplemental_area)
        keys = sorted({
            districts["features"][i]["properties"]["clave"]
            for i in matching_district_indices(supplemental_area, district_geometries, district_tree)
        })
        if not keys:
            raise ValueError("Barrio España no coincide con ningún distrito")
        mea16 = next(feature["properties"] for feature in new_features
                     if feature["properties"]["codigo"] == "MEA16")
        new_features.append({"type": "Feature", "geometry": supplemental_geometry,
                             "properties": {**mea16, "territorios": keys}})

    unchanged = [feature for feature in old_systems["features"]
                 if feature["properties"]["codigo"] not in categories
                 and feature["properties"]["codigo"] not in MERGED_SYSTEMS]
    systems = {"type": "FeatureCollection", "features": unchanged + new_features}

    criteria_features = []
    unresolved = 0
    for row, geometry in load_shapefile(args.criteria):
        code = normalize_code(row.get("codigo_sis"))
        if code not in categories:
            raise ValueError(f"Criterio sin sistema en capacidad nueva: {code}")
        candidates = zones[zone_key(code, row.get("zonas", ""))]
        if not candidates:
            candidates = [candidate for group, entries in zones.items()
                          if group[0] == code for candidate in entries]
        # Si hay varias zonas homónimas, usar la mayor intersección geométrica.
        source_geometry = shape(geometry)
        matches = sorted(candidates, key=lambda candidate: source_geometry.intersection(candidate[1]).area, reverse=True)
        best = matches[0][0] if matches and source_geometry.intersection(matches[0][1]).area > 0 else None
        if best is None:
            unresolved += 1
        props = {
            "codigo_sistema": public_code(code),
            "nombre_sistema": clean(row.get("nombre_sis")) or old_by_code[code]["nombre"],
            "codigo_abastecimiento": clean(best.get("Codigo_Aba")) if best else "No disponible en fuente",
            "zona": clean(row.get("zonas")),
            "zona_operativa": clean(best.get("Zona_Opera")) if best else "No disponible en fuente",
            **special_condition(row.get("cond_espec")),
        }
        criteria_features.append({"type": "Feature", "geometry": geometry, "properties": props})

    all_by_code = {feature["properties"]["codigo"]: feature["properties"] for feature in systems["features"]}
    metadata = json.loads((data_dir / "metadata.json").read_text(encoding="utf-8"))
    metadata["generatedAt"] = datetime.now(timezone.utc).isoformat()
    metadata["shapefileLayersUpdatedAt"] = metadata["generatedAt"]
    metadata["systems"] = len(all_by_code)
    metadata["regions"] = len({p["region"] for p in all_by_code.values()})
    metadata["categoryCounts"] = dict(sorted(Counter(p["ich"] for p in all_by_code.values()).items()))
    metadata["featureCounts"]["systems"] = len(systems["features"])
    metadata["featureCounts"]["criterios-especiales"] = len(criteria_features)

    with gzip.open(data_dir / "sistemas.geojson.gz", "wt", encoding="utf-8", compresslevel=9) as target:
        json.dump(systems, target, ensure_ascii=False, separators=(",", ":"))
    (data_dir / "criterios-especiales.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": criteria_features}, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    (data_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({"systems": len(all_by_code), "capacityPolygons": len(systems["features"]),
                      "sourceCapacityPolygons": len(capacity_rows),
                      "supplementalMergedAreas": int(not supplemental_area.is_empty),
                      "criteriaPolygons": len(criteria_features),
                      "criteriaWithoutZoneMatch": unresolved,
                      "mergedSystemsRemoved": sorted(set(old_by_code) & MERGED_SYSTEMS.keys()),
                      "retainedMetropolitanSystems": sorted(code for code in all_by_code if code.startswith("MEA") and code not in categories)},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
