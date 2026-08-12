#!/usr/bin/env python3
"""Importa ASADAS y distritos nacionales y precalcula relaciones territoriales.

La conversión conserva todos los vértices del SHP, redondea coordenadas WGS84 a
seis decimales y limita los atributos publicados. Las intersecciones de sistemas
y coberturas Thiessen se calculan con Shapely para que el navegador solo compare
claves territoriales al aplicar los filtros Provincia > Cantón > Distrito.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import re
import struct
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from shapely import make_valid
from shapely.geometry import shape
from shapely.strtree import STRtree


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "map" / "data"
DEFAULT_SYSTEMS = DATA_DIR / "sistemas.geojson.gz"
DEFAULT_THIESSEN = DATA_DIR / "cobertura-thiessen-asadas.geojson.gz"
DEFAULT_ASADAS = DATA_DIR / "asadas.geojson.gz"
DEFAULT_DISTRICTS = DATA_DIR / "distritos.geojson.gz"
DEFAULT_METADATA = DATA_DIR / "metadata.json"
PLACEHOLDER_NAMES = {"", "AAAAA", "N/D", "NO INDICADO"}


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", "" if value is None else str(value)).strip()


def normalized(value: Any) -> str:
    text = unicodedata.normalize("NFD", clean(value).upper())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return re.sub(r"[^A-Z0-9]", "", text)


def human_name(value: Any) -> str:
    text = clean(value)
    if not text or not text.isupper():
        return text
    words = text.title().split()
    connectors = {"De", "Del", "La", "Las", "El", "Los", "Y", "O"}
    return " ".join(
        word.lower() if index and word in connectors else word
        for index, word in enumerate(words)
    )


def territory_key(province: Any, canton: Any, district: Any) -> str:
    return "|".join(normalized(value) for value in (province, canton, district))


def decode_dbf(raw: bytes) -> str:
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_dbf(path: Path) -> list[dict[str, Any]]:
    data = path.read_bytes()
    record_count = struct.unpack_from("<I", data, 4)[0]
    header_length = struct.unpack_from("<H", data, 8)[0]
    record_length = struct.unpack_from("<H", data, 10)[0]
    fields: list[tuple[str, str, int, int]] = []
    position = 32
    while position < header_length and data[position] != 0x0D:
        descriptor = data[position : position + 32]
        raw_name = descriptor[:11].split(b"\x00", 1)[0]
        fields.append(
            (
                decode_dbf(raw_name),
                chr(descriptor[11]),
                descriptor[16],
                descriptor[17],
            )
        )
        position += 32

    records: list[dict[str, Any]] = []
    offset = header_length
    for record_number in range(1, record_count + 1):
        record = data[offset : offset + record_length]
        offset += record_length
        if not record or record[0:1] == b"*":
            raise ValueError(f"El DBF contiene un registro eliminado: {record_number}")
        cursor = 1
        row: dict[str, Any] = {}
        for name, field_type, length, decimals in fields:
            raw = record[cursor : cursor + length]
            cursor += length
            text = decode_dbf(raw).strip()
            if not text:
                value: Any = None
            elif field_type in {"N", "F"}:
                value = float(text) if decimals else int(float(text))
            else:
                value = text
            row[name] = value
        records.append(row)
    return records


def signed_area(ring: list[list[float]]) -> float:
    return 0.5 * sum(
        first[0] * second[1] - second[0] * first[1]
        for first, second in zip(ring, ring[1:])
    )


def ring_bounds(ring: list[list[float]]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    return min(xs), min(ys), max(xs), max(ys)


def point_in_ring(point: list[float], ring: list[list[float]]) -> bool:
    x, y = point
    inside = False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            intersection = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < intersection:
                inside = not inside
        previous = current
    return inside


def normalize_ring(
    points: list[tuple[float, float]], precision: int = 6
) -> list[list[float]]:
    ring: list[list[float]] = []
    for longitude, latitude in points:
        current = [round(longitude, precision), round(latitude, precision)]
        if not ring or current != ring[-1]:
            ring.append(current)
    if ring and ring[0] != ring[-1]:
        ring.append(ring[0].copy())
    return ring if len(ring) >= 4 else []


def rings_to_geometry(rings: list[list[list[float]]]) -> dict[str, Any]:
    valid = [ring for ring in rings if len(ring) >= 4 and signed_area(ring) != 0]
    if not valid:
        raise ValueError("La geometría no contiene anillos válidos.")

    exteriors = [ring for ring in valid if signed_area(ring) < 0]
    holes = [ring for ring in valid if signed_area(ring) > 0]
    if not exteriors:
        exteriors, holes = valid, []
    polygons = [[ring] for ring in exteriors]
    exterior_info = [
        (index, ring_bounds(ring), abs(signed_area(ring)), ring)
        for index, ring in enumerate(exteriors)
    ]
    for hole in holes:
        candidates = []
        for index, bounds, area, exterior in exterior_info:
            west, south, east, north = bounds
            point = hole[0]
            if (
                west <= point[0] <= east
                and south <= point[1] <= north
                and point_in_ring(point, exterior)
            ):
                candidates.append((area, index))
        if candidates:
            _, polygon_index = min(candidates)
            polygons[polygon_index].append(hole)
        else:
            polygons.append([hole])
    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": polygons}


def iter_polygon_shapefile(path: Path) -> Iterator[dict[str, Any]]:
    data = path.read_bytes()
    if struct.unpack_from(">i", data, 0)[0] != 9994:
        raise ValueError(f"{path.name}: cabecera SHP inválida.")
    if struct.unpack_from("<i", data, 32)[0] not in {5, 15, 25}:
        raise ValueError(f"{path.name}: se esperaba un SHP poligonal.")
    position = 100
    while position + 8 <= len(data):
        record_number, content_words = struct.unpack_from(">ii", data, position)
        start = position + 8
        end = start + content_words * 2
        if end > len(data):
            raise ValueError(f"Registro SHP incompleto: {record_number}")
        shape_type = struct.unpack_from("<i", data, start)[0]
        if shape_type == 0:
            yield {}
            position = end
            continue
        part_count, point_count = struct.unpack_from("<ii", data, start + 36)
        parts_start = start + 44
        parts = list(struct.unpack_from(f"<{part_count}i", data, parts_start))
        points_start = parts_start + part_count * 4
        raw_points = [
            struct.unpack_from("<2d", data, points_start + index * 16)
            for index in range(point_count)
        ]
        parts.append(point_count)
        rings = [
            normalize_ring(raw_points[parts[index] : parts[index + 1]])
            for index in range(part_count)
        ]
        yield rings_to_geometry([ring for ring in rings if ring])
        position = end


def iter_point_shapefile(path: Path) -> Iterator[list[float] | None]:
    data = path.read_bytes()
    if struct.unpack_from(">i", data, 0)[0] != 9994:
        raise ValueError(f"{path.name}: cabecera SHP inválida.")
    if struct.unpack_from("<i", data, 32)[0] not in {1, 11, 21}:
        raise ValueError(f"{path.name}: se esperaba un SHP de puntos.")
    position = 100
    while position + 8 <= len(data):
        record_number, content_words = struct.unpack_from(">ii", data, position)
        start = position + 8
        end = start + content_words * 2
        if end > len(data):
            raise ValueError(f"Registro SHP incompleto: {record_number}")
        shape_type = struct.unpack_from("<i", data, start)[0]
        if shape_type == 0:
            yield None
        else:
            longitude, latitude = struct.unpack_from("<2d", data, start + 4)
            yield [round(longitude, 6), round(latitude, 6)]
        position = end


def read_collection(path: Path) -> dict[str, Any]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as source:
            return json.load(source)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_collection(path: Path, collection: dict[str, Any]) -> None:
    payload = (
        json.dumps(collection, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".gz":
        buffer = io.BytesIO()
        with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as target:
            target.write(payload)
        path.write_bytes(buffer.getvalue())
    else:
        path.write_bytes(payload)


def safe_geometry(geometry: dict[str, Any]):
    result = shape(geometry)
    return result if result.is_valid else make_valid(result)


def district_collection(shapefile: Path) -> dict[str, Any]:
    rows = read_dbf(shapefile.with_suffix(".dbf"))
    geometries = list(iter_polygon_shapefile(shapefile))
    if len(rows) != len(geometries):
        raise ValueError("Distritos: SHP y DBF tienen cantidades distintas.")

    canton_by_code: dict[str, str] = {}
    for row in rows:
        code = clean(row.get("coddistful"))
        canton = clean(row.get("nom_cant"))
        if len(code) >= 3 and normalized(canton) not in PLACEHOLDER_NAMES:
            canton_by_code.setdefault(code[:3], canton)

    features = []
    seen_keys: set[str] = set()
    for row, geometry in zip(rows, geometries):
        if not geometry:
            continue
        code = clean(row.get("coddistful"))
        province = human_name(row.get("nom_prov"))
        canton_source = clean(row.get("nom_cant"))
        if normalized(canton_source) in PLACEHOLDER_NAMES:
            canton_source = canton_by_code.get(code[:3], canton_source)
        canton = human_name(canton_source)
        district = human_name(row.get("nom_distr"))
        key = territory_key(province, canton, district)
        if not all((province, canton, district, key)):
            raise ValueError(f"Distrito con identificación incompleta: {row}")
        if key in seen_keys:
            raise ValueError(f"Distrito duplicado por nombre: {province}, {canton}, {district}")
        seen_keys.add(key)
        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": {
                    "clave": key,
                    "codigo": code,
                    "provincia": province,
                    "canton": canton,
                    "distrito": district,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def district_index(districts: dict[str, Any]):
    geometries = [safe_geometry(feature["geometry"]) for feature in districts["features"]]
    return geometries, STRtree(geometries)


def matching_district_indices(geometry, geometries, tree: STRtree) -> list[int]:
    matches = []
    for candidate in tree.query(geometry):
        index = int(candidate)
        if geometry.intersects(geometries[index]):
            matches.append(index)
    return matches


def parse_operator(value: Any) -> tuple[str, str]:
    source = clean(value)
    match = re.match(r"^(\d{5}-\d{4})\s*-\s*(.+)$", source)
    if match:
        return match.group(1), clean(match.group(2))
    return "", source


def asada_collection(
    shapefile: Path,
    districts: dict[str, Any],
    district_geometries,
    district_tree: STRtree,
) -> tuple[dict[str, Any], Counter[str]]:
    rows = read_dbf(shapefile.with_suffix(".dbf"))
    points = list(iter_point_shapefile(shapefile))
    if len(rows) != len(points):
        raise ValueError("ASADAS: SHP y DBF tienen cantidades distintas.")

    lookup = {
        territory_key(p["provincia"], p["canton"], p["distrito"]): p["clave"]
        for p in (feature["properties"] for feature in districts["features"])
    }
    methods: Counter[str] = Counter()
    features = []
    for row, coordinates in zip(rows, points):
        if coordinates is None:
            continue
        geometry = shape({"type": "Point", "coordinates": coordinates})
        candidates = matching_district_indices(geometry, district_geometries, district_tree)
        source_key = territory_key(row.get("Provincia"), row.get("Cantón"), row.get("Distrito"))
        territory = ""
        if candidates:
            candidate_keys = [
                districts["features"][index]["properties"]["clave"]
                for index in candidates
            ]
            territory = source_key if source_key in candidate_keys else candidate_keys[0]
            methods["geoespacial"] += 1
        elif source_key in lookup:
            territory = lookup[source_key]
            methods["respaldo_administrativo"] += 1
        else:
            methods["sin_asignar"] += 1
        code, name = parse_operator(row.get("Ente_Opera"))
        if not name:
            raise ValueError("Se encontró un punto ASADA sin nombre de operador.")
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": coordinates},
                "properties": {
                    "codigo": code,
                    "nombre": name,
                    "territorio": territory,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}, methods


def annotate_polygon_collection(
    collection: dict[str, Any],
    districts: dict[str, Any],
    district_geometries,
    district_tree: STRtree,
) -> dict[str, Any]:
    for feature in collection.get("features", []):
        geometry = feature.get("geometry")
        if not geometry:
            feature.setdefault("properties", {})["territorios"] = []
            continue
        source_geometry = safe_geometry(geometry)
        indices = matching_district_indices(
            source_geometry, district_geometries, district_tree
        )
        keys = sorted(
            {
                districts["features"][index]["properties"]["clave"]
                for index in indices
            }
        )
        feature.setdefault("properties", {})["territorios"] = keys
    return collection


def update_metadata(
    path: Path,
    asadas: dict[str, Any],
    districts: dict[str, Any],
    systems: dict[str, Any],
    thiessen: dict[str, Any],
) -> None:
    metadata = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    counts = metadata.setdefault("featureCounts", {})
    counts.update(
        {
            "systems": len(systems.get("features", [])),
            "asadas": len(asadas.get("features", [])),
            "cobertura-thiessen-asadas": len(thiessen.get("features", [])),
            "districts": len(districts.get("features", [])),
        }
    )
    metadata["generatedAt"] = datetime.now(timezone.utc).isoformat()
    metadata["territorialFilters"] = {
        "provinces": len(
            {f["properties"]["provincia"] for f in districts["features"]}
        ),
        "cantons": len(
            {
                (f["properties"]["provincia"], f["properties"]["canton"])
                for f in districts["features"]
            }
        ),
        "districts": len(districts["features"]),
    }
    path.write_text(
        json.dumps(metadata, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asadas-shapefile", required=True, type=Path)
    parser.add_argument("--districts-shapefile", required=True, type=Path)
    parser.add_argument("--systems", type=Path, default=DEFAULT_SYSTEMS)
    parser.add_argument("--thiessen", type=Path, default=DEFAULT_THIESSEN)
    parser.add_argument(
        "--thiessen-output",
        type=Path,
        help="Salida opcional; por defecto actualiza el mismo archivo de entrada.",
    )
    parser.add_argument("--asadas-output", type=Path, default=DEFAULT_ASADAS)
    parser.add_argument("--districts-output", type=Path, default=DEFAULT_DISTRICTS)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    args = parser.parse_args()

    districts = district_collection(args.districts_shapefile.resolve())
    district_geometries, district_tree = district_index(districts)
    asadas, assignment_methods = asada_collection(
        args.asadas_shapefile.resolve(),
        districts,
        district_geometries,
        district_tree,
    )
    systems = annotate_polygon_collection(
        read_collection(args.systems.resolve()),
        districts,
        district_geometries,
        district_tree,
    )
    thiessen = annotate_polygon_collection(
        read_collection(args.thiessen.resolve()),
        districts,
        district_geometries,
        district_tree,
    )

    write_collection(args.districts_output.resolve(), districts)
    write_collection(args.asadas_output.resolve(), asadas)
    write_collection(args.systems.resolve(), systems)
    thiessen_output = (args.thiessen_output or args.thiessen).resolve()
    write_collection(thiessen_output, thiessen)
    update_metadata(
        args.metadata.resolve(), asadas, districts, systems, thiessen
    )

    print(
        json.dumps(
            {
                "status": "ok",
                "asadaPoints": len(asadas["features"]),
                "asadaOperators": len(
                    {f["properties"]["nombre"] for f in asadas["features"]}
                ),
                "districts": len(districts["features"]),
                "asadaTerritoryAssignment": dict(assignment_methods),
                "systemsWithTerritory": sum(
                    bool(f["properties"]["territorios"])
                    for f in systems["features"]
                ),
                "thiessenWithTerritory": sum(
                    bool(f["properties"]["territorios"])
                    for f in thiessen["features"]
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
