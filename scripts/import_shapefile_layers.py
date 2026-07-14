#!/usr/bin/env python3
"""Importa SHP públicos sin simplificar geometrías ni eliminar vértices.

El conversor usa únicamente la biblioteca estándar de Python. Acepta un ZIP con
un único Shapefile y publica solamente los atributos autorizados para el visor.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import struct
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "map" / "data"
GAM_BOUNDS = (-84.66, 9.48, -83.76, 10.19)
MAX_ARCHIVE_BYTES = 200_000_000


@dataclass(frozen=True)
class ShapefileBundle:
    shp: bytes
    dbf: bytes
    prj: str
    cpg: str
    source_name: str


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def normalized_text(value: object) -> str:
    plain = unicodedata.normalize("NFD", clean(value))
    return "".join(char for char in plain if unicodedata.category(char) != "Mn")


def normalize_code(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", clean(value).upper())


def public_code(value: object) -> str:
    normalized = normalize_code(value)
    match = re.fullmatch(r"MEA(\d{2})", normalized)
    return f"ME-A-{match.group(1)}" if match else clean(value)


def special_condition(value: object) -> dict[str, str]:
    raw = clean(value)
    plain = normalized_text(raw)
    article = re.search(r"articulo\s*(\d+)", plain, re.IGNORECASE)
    if article:
        return {"tipo": "Facilidad", "detalle": f"Artículo {article.group(1)}"}
    if re.search(r"restric", plain, re.IGNORECASE):
        return {"tipo": "Restricción", "detalle": raw or "Restricción particular"}
    return {"tipo": "Criterio especial", "detalle": raw or "No especificado"}


def _safe_archive_names(archive: zipfile.ZipFile) -> list[str]:
    names = archive.namelist()
    if sum(item.file_size for item in archive.infolist()) > MAX_ARCHIVE_BYTES:
        raise ValueError("El ZIP supera el tamaño máximo permitido para importación.")
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"El ZIP contiene una ruta no segura: {name}")
    return names


def _matching_member(names: list[str], stem: str, suffix: str) -> str | None:
    target = f"{stem}{suffix}".casefold()
    return next((name for name in names if name.casefold() == target), None)


def read_bundle(path: Path) -> ShapefileBundle:
    if path.suffix.casefold() == ".zip":
        with zipfile.ZipFile(path) as archive:
            names = _safe_archive_names(archive)
            shapefiles = [name for name in names if name.casefold().endswith(".shp")]
            if len(shapefiles) != 1:
                raise ValueError(
                    f"{path.name} debe contener exactamente un archivo .shp."
                )
            shp_name = shapefiles[0]
            stem = shp_name[:-4]
            dbf_name = _matching_member(names, stem, ".dbf")
            prj_name = _matching_member(names, stem, ".prj")
            cpg_name = _matching_member(names, stem, ".cpg")
            if not dbf_name or not prj_name:
                raise ValueError(f"{path.name} debe incluir los archivos .dbf y .prj.")
            return ShapefileBundle(
                shp=archive.read(shp_name),
                dbf=archive.read(dbf_name),
                prj=archive.read(prj_name).decode("utf-8-sig", errors="replace"),
                cpg=(
                    archive.read(cpg_name).decode("ascii", errors="replace").strip()
                    if cpg_name
                    else "UTF-8"
                ),
                source_name=PurePosixPath(shp_name).name,
            )

    if path.suffix.casefold() != ".shp":
        raise ValueError("La fuente debe ser un ZIP de Shapefile o un archivo .shp.")
    siblings = {item.suffix.casefold(): item for item in path.parent.glob(f"{path.stem}.*")}
    if ".dbf" not in siblings or ".prj" not in siblings:
        raise ValueError(f"{path.name} debe estar acompañado por .dbf y .prj.")
    return ShapefileBundle(
        shp=path.read_bytes(),
        dbf=siblings[".dbf"].read_bytes(),
        prj=siblings[".prj"].read_text(encoding="utf-8-sig", errors="replace"),
        cpg=(
            siblings[".cpg"].read_text(encoding="ascii", errors="replace").strip()
            if ".cpg" in siblings
            else "UTF-8"
        ),
        source_name=path.name,
    )


def _dbf_encoding(cpg: str) -> str:
    token = cpg.strip().strip('"').upper()
    if token in {"65001", "UTF8", "UTF-8"}:
        return "utf-8"
    return token or "utf-8"


def read_dbf(data: bytes, encoding: str) -> list[dict[str, str] | None]:
    if len(data) < 33:
        raise ValueError("El DBF está incompleto.")
    record_count = struct.unpack_from("<I", data, 4)[0]
    header_length = struct.unpack_from("<H", data, 8)[0]
    record_length = struct.unpack_from("<H", data, 10)[0]
    fields: list[tuple[str, int]] = []
    cursor = 32
    while cursor < header_length and data[cursor] != 0x0D:
        descriptor = data[cursor : cursor + 32]
        if len(descriptor) != 32:
            raise ValueError("El encabezado DBF está incompleto.")
        name = descriptor[:11].split(b"\0", 1)[0].decode("ascii", errors="ignore")
        fields.append((name, descriptor[16]))
        cursor += 32

    rows: list[dict[str, str] | None] = []
    for index in range(record_count):
        start = header_length + index * record_length
        record = data[start : start + record_length]
        if len(record) != record_length:
            raise ValueError("El DBF termina antes del último registro declarado.")
        if record[:1] == b"*":
            rows.append(None)
            continue
        values: dict[str, str] = {}
        offset = 1
        for name, length in fields:
            raw = record[offset : offset + length]
            offset += length
            values[name] = raw.decode(encoding, errors="replace").strip()
        rows.append(values)
    return rows


def _inverse_crtm05(easting: float, northing: float) -> tuple[float, float]:
    semi_major = 6_378_137.0
    flattening = 1 / 298.257223563
    eccentricity_sq = flattening * (2 - flattening)
    second_eccentricity_sq = eccentricity_sq / (1 - eccentricity_sq)
    scale = 0.9999
    central_meridian = math.radians(-84.0)
    first_eccentricity = (
        (1 - math.sqrt(1 - eccentricity_sq))
        / (1 + math.sqrt(1 - eccentricity_sq))
    )

    meridional_arc = northing / scale
    mu = meridional_arc / (
        semi_major
        * (
            1
            - eccentricity_sq / 4
            - 3 * eccentricity_sq**2 / 64
            - 5 * eccentricity_sq**3 / 256
        )
    )
    footprint = (
        mu
        + (3 * first_eccentricity / 2 - 27 * first_eccentricity**3 / 32)
        * math.sin(2 * mu)
        + (21 * first_eccentricity**2 / 16 - 55 * first_eccentricity**4 / 32)
        * math.sin(4 * mu)
        + 151 * first_eccentricity**3 / 96 * math.sin(6 * mu)
        + 1097 * first_eccentricity**4 / 512 * math.sin(8 * mu)
    )
    sin_footprint = math.sin(footprint)
    cos_footprint = math.cos(footprint)
    tangent_sq = math.tan(footprint) ** 2
    curve = second_eccentricity_sq * cos_footprint**2
    prime_vertical = semi_major / math.sqrt(
        1 - eccentricity_sq * sin_footprint**2
    )
    meridional_radius = (
        semi_major
        * (1 - eccentricity_sq)
        / (1 - eccentricity_sq * sin_footprint**2) ** 1.5
    )
    distance = (easting - 500_000.0) / (prime_vertical * scale)

    latitude = footprint - (
        prime_vertical
        * math.tan(footprint)
        / meridional_radius
        * (
            distance**2 / 2
            - (5 + 3 * tangent_sq + 10 * curve - 4 * curve**2 - 9 * second_eccentricity_sq)
            * distance**4
            / 24
            + (
                61
                + 90 * tangent_sq
                + 298 * curve
                + 45 * tangent_sq**2
                - 252 * second_eccentricity_sq
                - 3 * curve**2
            )
            * distance**6
            / 720
        )
    )
    longitude = central_meridian + (
        distance
        - (1 + 2 * tangent_sq + curve) * distance**3 / 6
        + (
            5
            - 2 * curve
            + 28 * tangent_sq
            - 3 * curve**2
            + 8 * second_eccentricity_sq
            + 24 * tangent_sq**2
        )
        * distance**5
        / 120
    ) / cos_footprint
    return math.degrees(longitude), math.degrees(latitude)


def _inverse_web_mercator(easting: float, northing: float) -> tuple[float, float]:
    """Convierte EPSG:3857 a coordenadas geográficas WGS84."""

    radius = 6_378_137.0
    longitude = math.degrees(easting / radius)
    latitude = math.degrees(2 * math.atan(math.exp(northing / radius)) - math.pi / 2)
    return longitude, latitude


def coordinate_transform(prj: str) -> Callable[[float, float], tuple[float, float]]:
    plain = normalized_text(prj).upper()
    if "CRTM05" in plain:
        return _inverse_crtm05
    if "WEB_MERCATOR" in plain or "MERCATOR_AUXILIARY_SPHERE" in plain:
        return _inverse_web_mercator
    if "WGS_1984" in plain and "PROJCS" not in plain:
        return lambda longitude, latitude: (longitude, latitude)
    raise ValueError(
        "El sistema de coordenadas no es WGS84 geográfico, CRTM05 ni Web Mercator."
    )


def _signed_area(ring: list[list[float]]) -> float:
    return sum(
        first[0] * second[1] - second[0] * first[1]
        for first, second in zip(ring, ring[1:])
    ) / 2


def _point_in_ring(point: list[float], ring: list[list[float]]) -> bool:
    x, y = point
    inside = False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            crossing = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing:
                inside = not inside
        previous = current
    return inside


def _polygon_geometry(rings: list[list[list[float]]]) -> dict[str, object]:
    outer_rings = [ring for ring in rings if _signed_area(ring) <= 0]
    holes = [ring for ring in rings if _signed_area(ring) > 0]
    if not outer_rings:
        outer_rings = [max(rings, key=lambda ring: abs(_signed_area(ring)))]
        holes = [ring for ring in rings if ring is not outer_rings[0]]

    polygons: list[list[list[list[float]]]] = [[outer] for outer in outer_rings]
    outer_areas = [abs(_signed_area(outer)) for outer in outer_rings]
    for hole in holes:
        candidates = [
            index
            for index, outer in enumerate(outer_rings)
            if _point_in_ring(hole[0], outer)
        ]
        if not candidates:
            polygons.append([hole])
            continue
        parent = min(candidates, key=lambda index: outer_areas[index])
        polygons[parent].append(hole)

    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": polygons}


def read_shp(
    data: bytes,
    transform: Callable[[float, float], tuple[float, float]],
) -> list[dict[str, object] | None]:
    if len(data) < 100 or struct.unpack_from(">I", data, 0)[0] != 9994:
        raise ValueError("El archivo SHP no tiene un encabezado válido.")
    geometries: list[dict[str, object] | None] = []
    cursor = 100
    while cursor + 8 <= len(data):
        _record_number, content_words = struct.unpack_from(">II", data, cursor)
        content_length = content_words * 2
        body = data[cursor + 8 : cursor + 8 + content_length]
        if len(body) != content_length:
            raise ValueError("El SHP contiene un registro incompleto.")
        cursor += 8 + content_length
        shape_type = struct.unpack_from("<I", body, 0)[0]
        if shape_type == 0:
            geometries.append(None)
            continue
        if shape_type not in {5, 15, 25}:
            raise ValueError(f"Tipo de geometría SHP no compatible: {shape_type}")
        part_count, point_count = struct.unpack_from("<2i", body, 36)
        parts = list(struct.unpack_from(f"<{part_count}i", body, 44))
        point_offset = 44 + part_count * 4
        source_points = [
            struct.unpack_from("<2d", body, point_offset + index * 16)
            for index in range(point_count)
        ]
        # Ocho decimales en WGS84 conservan precisión milimétrica aproximada y
        # evitan almacenar ruido numérico propio de la reproyección.
        points = [
            [round(longitude, 8), round(latitude, 8)]
            for longitude, latitude in (transform(x, y) for x, y in source_points)
        ]
        rings = [
            points[start : parts[index + 1] if index + 1 < part_count else point_count]
            for index, start in enumerate(parts)
        ]
        if any(len(ring) < 4 or ring[0] != ring[-1] for ring in rings):
            raise ValueError("El SHP contiene un anillo poligonal abierto o incompleto.")
        geometries.append(_polygon_geometry(rings))
    return geometries


def _value(row: dict[str, str], *names: str) -> str:
    lowered = {key.casefold(): value for key, value in row.items()}
    return next((clean(lowered.get(name.casefold())) for name in names if clean(lowered.get(name.casefold()))), "")


def criteria_properties(row: dict[str, str]) -> dict[str, str]:
    return {
        "codigo_sistema": public_code(_value(row, "codigo_sis")),
        "nombre_sistema": _value(row, "nombre_sis") or "Sin nombre",
        "codigo_abastecimiento": _value(row, "codigo_aba"),
        "zona": _value(row, "zonas"),
        "zona_operativa": _value(row, "zona_opera"),
        **special_condition(_value(row, "cond_espec")),
    }


def thiessen_properties(row: dict[str, str]) -> dict[str, str]:
    return {
        "codigo": _value(row, "id_inec", "codigo_dta"),
        "referencia": _value(row, "nomb_comp", "nombre_loc") or "Área estimada ASADA",
        "provincia": _value(row, "provincia"),
        "canton": _value(row, "canton"),
        "distrito": _value(row, "distrito"),
        "alcance": "Cobertura somera/estimada",
        "metodo": "Polígono de Thiessen",
    }


def municipal_properties(row: dict[str, str]) -> dict[str, str]:
    return {
        "operador": _value(row, "operador") or "Acueducto municipal",
        "sistema": _value(row, "sistema") or "Sin nombre",
    }


def ona_properties(row: dict[str, str]) -> dict[str, str]:
    return {
        "operador": _value(row, "operador") or "Organización de usuarios de agua",
        "sistema": _value(row, "sistema") or "Sin nombre",
    }


def intersects_gam(geometry: dict[str, object]) -> bool:
    coordinates = list(_walk_coordinates(geometry.get("coordinates")))
    if not coordinates:
        return False
    minimum_x = min(point[0] for point in coordinates)
    minimum_y = min(point[1] for point in coordinates)
    maximum_x = max(point[0] for point in coordinates)
    maximum_y = max(point[1] for point in coordinates)
    west, south, east, north = GAM_BOUNDS
    return not (
        maximum_x < west
        or minimum_x > east
        or maximum_y < south
        or minimum_y > north
    )


def import_layer(path: Path, layer_name: str) -> tuple[dict[str, object], dict[str, object]]:
    bundle = read_bundle(path)
    rows = read_dbf(bundle.dbf, _dbf_encoding(bundle.cpg))
    geometries = read_shp(bundle.shp, coordinate_transform(bundle.prj))
    if len(rows) != len(geometries):
        raise ValueError(
            f"{bundle.source_name}: DBF y SHP tienen distinta cantidad de registros."
        )
    mappers = {
        "criteria": criteria_properties,
        "thiessen": thiessen_properties,
        "municipal": municipal_properties,
        "ona": ona_properties,
    }
    mapper = mappers[layer_name]
    features = []
    for row, geometry in zip(rows, geometries):
        if row is None or geometry is None:
            continue
        if layer_name in {"municipal", "ona"} and not intersects_gam(geometry):
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": mapper(row),
            }
        )
    vertex_count = sum(
        1
        for feature in features
        for _coordinate in _walk_coordinates(feature["geometry"]["coordinates"])
    )
    return (
        {"type": "FeatureCollection", "features": features},
        {
            "source": bundle.source_name,
            "sourceRecords": len(rows),
            "publishedFeatures": len(features),
            "vertices": vertex_count,
        },
    )


def _walk_coordinates(value: object):
    if (
        isinstance(value, list)
        and len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    ):
        yield value
        return
    if isinstance(value, list):
        for child in value:
            yield from _walk_coordinates(child)


def write_collection(path: Path, collection: dict[str, object]) -> None:
    path.write_text(
        json.dumps(collection, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def update_metadata(output_dir: Path, summaries: dict[str, dict[str, object]]) -> None:
    metadata_path = output_dir / "metadata.json"
    if not metadata_path.exists():
        return
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    feature_counts = metadata.setdefault("featureCounts", {})
    if "criteria" in summaries:
        feature_counts["criterios-especiales"] = summaries["criteria"]["publishedFeatures"]
    if "thiessen" in summaries:
        feature_counts["cobertura-thiessen-asadas"] = summaries["thiessen"]["publishedFeatures"]
    if "municipal" in summaries:
        feature_counts["municipal"] = summaries["municipal"]["publishedFeatures"]
    if "ona" in summaries:
        feature_counts["ona"] = summaries["ona"]["publishedFeatures"]
    metadata["shapefileLayersUpdatedAt"] = datetime.now(timezone.utc).isoformat()
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Importa capas SHP originales sin simplificar sus geometrías."
    )
    parser.add_argument("--thiessen", type=Path, help="ZIP o SHP de cobertura Thiessen")
    parser.add_argument("--criteria", type=Path, help="ZIP o SHP de criterios especiales")
    parser.add_argument("--municipal", type=Path, help="ZIP o SHP de acueductos municipales")
    parser.add_argument("--ona", type=Path, help="ZIP o SHP de coberturas ONA/SUA")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    if not any((args.thiessen, args.criteria, args.municipal, args.ona)):
        parser.error("Indique al menos una capa SHP para importar.")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summaries: dict[str, dict[str, object]] = {}
    if args.thiessen:
        collection, summary = import_layer(args.thiessen, "thiessen")
        write_collection(args.output_dir / "cobertura-thiessen-asadas.geojson", collection)
        summaries["thiessen"] = summary
    if args.criteria:
        collection, summary = import_layer(args.criteria, "criteria")
        write_collection(args.output_dir / "criterios-especiales.geojson", collection)
        summaries["criteria"] = summary
    if args.municipal:
        collection, summary = import_layer(args.municipal, "municipal")
        write_collection(args.output_dir / "municipalidades.geojson", collection)
        summaries["municipal"] = summary
    if args.ona:
        collection, summary = import_layer(args.ona, "ona")
        write_collection(args.output_dir / "onas.geojson", collection)
        summaries["ona"] = summary
    update_metadata(args.output_dir, summaries)
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
