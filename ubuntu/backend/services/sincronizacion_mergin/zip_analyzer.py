import json
import logging
import re
import sqlite3
import unicodedata
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

try:
    from osgeo import ogr
except ImportError:  # pragma: no cover - fallback esperado cuando GDAL no esta instalado
    ogr = None

log = logging.getLogger(__name__)

TRANSFERABLE_LAYER_DEFINITIONS = [
    {"display_name": "ARB_Direccion", "category": "operational_spatial"},
    {"display_name": "ARB_Punto_de_Referencia", "category": "operational_spatial"},
    {"display_name": "ARB_Marca_predial", "category": "operational_spatial"},
    {"display_name": "ARB_Unidad_de_construccion", "category": "operational_spatial"},
    {"display_name": "ARB_Construccion", "category": "operational_spatial"},
    {"display_name": "ARB_Terreno", "category": "operational_spatial"},
    {"display_name": "ARB_Terreno_historico", "category": "operational_spatial"},
    {"display_name": "ARB_Predio", "category": "operational_table"},
    {"display_name": "ARB_Derecho_Interesado_Fuente", "category": "operational_table"},
    {"display_name": "ARB_Caracteristicas_de_la_unidad_de_construccion", "category": "operational_table"},
    {"display_name": "ARB_Informacion_PH", "category": "operational_table"},
    {"display_name": "ARB_Tramite", "category": "operational_table"},
    {"display_name": "ARB_Avaluo_Valor", "category": "operational_table"},
    {"display_name": "ARB_Referencia_Registral_del_Sistema_Antiguo_Valor", "category": "operational_table"},
    {"display_name": "ARB_Novedad_Numero_Predial_Valor", "category": "operational_table"},
    {"display_name": "ARB_Novedad_FMI_Valor", "category": "operational_table"},
    {"display_name": "T_ILI2DB_BASKET", "category": "operational_table"},
    {"display_name": "T_ILI2DB_DATASET", "category": "operational_table"},
]

BASE_GEOGRAPHIC_LAYER_NAMES = [
    "ARB_Terreno",
    "ARB_Construccion",
    "ARB_Unidad_de_construccion",
    "ARB_Direccion",
]

IGNORED_LAYER_TOKENS = [
    "adjunto",
    "attachment",
    "foto",
    "photo",
    "imagen",
    "image",
    "documento",
    "multimedia",
    "archivo",
    "file",
]

IGNORED_EXACT_NAMES = {"domains", "system"}
BOX_IGNORED_REASON = "Adjuntos, dominios o sistema no se transfieren; adjuntos/fotos se gestionan por Box."
WHITELIST_IGNORED_REASON = "No incluida en la whitelist transferible de Fase 3."
DOMAIN_CATALOG_REASON = "Catalogo LADM detectado por sufijo Tipo; se importa al staging para preservar referencias."


def normalize_layer_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(name or ""))
    normalized = normalized.replace("?", "n").replace("?", "N")
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = normalized.lower().replace("?", "n")
    normalized = normalized.replace(" ", "_")
    normalized = re.sub(r"[^a-z0-9_]", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_")


for definition in TRANSFERABLE_LAYER_DEFINITIONS:
    definition["normalized_name"] = normalize_layer_name(definition["display_name"])

NORMALIZED_TRANSFERABLE_LAYER_NAMES = {
    definition["normalized_name"]: definition
    for definition in TRANSFERABLE_LAYER_DEFINITIONS
}
PROTECTED_TRANSFERABLE_LAYER_NAMES = {
    normalize_layer_name("ARB_InteresadoDocumentoTipo"),
    normalize_layer_name("ARB_Predio"),
    normalize_layer_name("T_ILI2DB_BASKET"),
    normalize_layer_name("T_ILI2DB_DATASET"),
}
NORMALIZED_BASE_LAYER_NAMES = {
    normalize_layer_name(name): name
    for name in BASE_GEOGRAPHIC_LAYER_NAMES
}


def analyze_uploaded_zip(upload_file):
    filename = (upload_file.filename or "").strip() or "proyecto.zip"
    if not filename.lower().endswith(".zip"):
        raise ValueError("El archivo cargado debe ser un ZIP.")

    try:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            zip_path = temp_path / filename

            zip_bytes = upload_file.file.read()
            zip_path.write_bytes(zip_bytes)

            extract_dir = temp_path / "extracted"
            extract_dir.mkdir(parents=True, exist_ok=True)
            _extract_zip_safely(zip_path, extract_dir)

            discovered = _discover_project_files(extract_dir)
            analysis = _analyze_gpkgs(discovered["gpkg_paths"], extract_dir)
            metadata = _read_metadata(discovered["metadata_path"])

            return {
                "ok": True,
                "zip_name": filename,
                "metadata": metadata,
                "metadata_found": discovered["metadata_path"] is not None,
                "metadata_file": discovered["metadata_file"],
                "project_file_found": discovered["project_path"] is not None,
                "project_file": discovered["project_file"],
                "attachments_found": discovered["attachments_path"] is not None,
                "attachments_path": discovered["attachments_dir"],
                "gpkg_found": bool(discovered["gpkg_paths"]),
                "gpkg_files": analysis["gpkg_files"],
                "compatibility": analysis["compatibility"],
                "transferable_layers": analysis["transferable_layers"],
                "missing_transferable_layers": analysis["missing_transferable_layers"],
                "ignored_layers": analysis["ignored_layers"],
                "summary": analysis["summary"],
                "missing_required_layers": analysis["missing_required_layers"],
            }
    finally:
        upload_file.file.close()


def _extract_zip_safely(zip_path: Path, extract_dir: Path):
    extract_root = extract_dir.resolve()
    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.infolist():
            member_path = (extract_dir / member.filename).resolve()
            if extract_root not in member_path.parents and member_path != extract_root:
                raise ValueError("El ZIP contiene rutas no validas.")
        archive.extractall(extract_dir)


def _discover_project_files(root: Path):
    gpkg_paths = [
        path for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix.lower() == ".gpkg"
    ]
    metadata_path = _find_file_by_name(root, "metadata.json")
    project_path = _find_first_file_by_suffix(root, ".qgs", ".qgz")
    attachments_path = _find_directory_by_name(root, "attachments")

    return {
        "gpkg_paths": gpkg_paths,
        "metadata_path": metadata_path,
        "metadata_file": _relative_path(root, metadata_path),
        "project_path": project_path,
        "project_file": _relative_path(root, project_path),
        "attachments_path": attachments_path,
        "attachments_dir": _relative_path(root, attachments_path),
    }


def _find_first_file_by_suffix(root: Path, *suffixes):
    normalized = {suffix.lower() for suffix in suffixes}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in normalized:
            return path
    return None


def _find_file_by_name(root: Path, expected_name: str):
    expected = expected_name.lower()
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name.lower() == expected:
            return path
    return None


def _find_directory_by_name(root: Path, expected_name: str):
    expected = expected_name.lower()
    for path in sorted(root.rglob("*")):
        if path.is_dir() and path.name.lower() == expected:
            return path
    return None


def _relative_path(root: Path, path: Path | None):
    if not path:
        return ""
    return str(path.relative_to(root)).replace("\\", "/")


def _analyze_gpkgs(gpkg_paths, root: Path):
    transferable_layers = []
    ignored_layers = []
    gpkg_files = []
    found_transferable_names = set()
    transferable_records = 0
    ignored_records = 0

    for gpkg_path in gpkg_paths:
        relative_gpkg = _relative_path(root, gpkg_path)
        layers = _analyze_single_gpkg(gpkg_path)

        gpkg_transferable = 0
        gpkg_ignored = 0
        gpkg_transferable_records = 0
        gpkg_ignored_records = 0

        for layer in layers:
            classified = _classify_layer(relative_gpkg, layer)
            if classified.get("transferable"):
                transferable_layers.append(classified)
                found_transferable_names.add(classified["normalized_name"])
                transferable_records += classified["records"]
                gpkg_transferable += 1
                gpkg_transferable_records += classified["records"]
            else:
                ignored_layers.append(classified)
                ignored_records += classified["records"]
                gpkg_ignored += 1
                gpkg_ignored_records += classified["records"]

        gpkg_files.append(
            {
                "gpkg": relative_gpkg,
                "layer_count": len(layers),
                "transferable_layers": gpkg_transferable,
                "ignored_layers": gpkg_ignored,
                "transferable_records": gpkg_transferable_records,
                "ignored_records": gpkg_ignored_records,
                "category": "transferable" if gpkg_transferable > 0 else "ignored",
            }
        )

    missing_transferable_layers = [
        definition["display_name"]
        for definition in TRANSFERABLE_LAYER_DEFINITIONS
        if definition["normalized_name"] not in found_transferable_names
    ]
    missing_required_layers = [
        display_name
        for normalized_name, display_name in NORMALIZED_BASE_LAYER_NAMES.items()
        if normalized_name not in found_transferable_names
    ]

    if not missing_required_layers and any(
        normalized_name in found_transferable_names
        for normalized_name in NORMALIZED_BASE_LAYER_NAMES
    ):
        compatibility = "Compatible"
    elif transferable_layers:
        compatibility = "Compatible parcial"
    else:
        compatibility = "No compatible"

    return {
        "compatibility": compatibility,
        "transferable_layers": transferable_layers,
        "missing_transferable_layers": missing_transferable_layers,
        "ignored_layers": ignored_layers,
        "gpkg_files": gpkg_files,
        "missing_required_layers": missing_required_layers,
        "summary": {
            "total_gpkg": len(gpkg_paths),
            "transferable_layers": len(transferable_layers),
            "missing_transferable_layers": len(missing_transferable_layers),
            "ignored_layers": len(ignored_layers),
            "transferable_records": transferable_records,
            "ignored_records": ignored_records,
        },
    }


def _classify_layer(gpkg_relative_path: str, layer):
    layer_name = layer["name"]
    normalized_layer_name = normalize_layer_name(layer_name)
    normalized_gpkg = normalize_layer_name(gpkg_relative_path)

    if _should_ignore_by_box(normalized_layer_name, normalized_gpkg):
        return {
            "name": layer_name,
            "gpkg": gpkg_relative_path,
            "records": layer["records"],
            "geometry": layer["geometry"],
            "crs": layer["crs"],
            "extent": layer["extent"],
            "category": "ignored",
            "reason": BOX_IGNORED_REASON,
        }

    definition = NORMALIZED_TRANSFERABLE_LAYER_NAMES.get(normalized_layer_name)
    if definition is not None:
        return {
            "name": layer_name,
            "normalized_name": definition["normalized_name"],
            "expected_display_name": definition["display_name"],
            "gpkg": gpkg_relative_path,
            "records": layer["records"],
            "geometry": layer["geometry"],
            "crs": layer["crs"],
            "extent": layer["extent"],
            "category": definition["category"],
            "transferable": True,
        }

    if _is_domain_catalog_layer(layer_name, normalized_layer_name):
        return {
            "name": layer_name,
            "normalized_name": normalized_layer_name,
            "expected_display_name": layer_name,
            "gpkg": gpkg_relative_path,
            "records": layer["records"],
            "geometry": layer["geometry"],
            "crs": layer["crs"],
            "extent": layer["extent"],
            "category": "domain_catalog",
            "reason": DOMAIN_CATALOG_REASON,
            "transferable": True,
        }

    return {
        "name": layer_name,
        "gpkg": gpkg_relative_path,
        "records": layer["records"],
        "geometry": layer["geometry"],
        "crs": layer["crs"],
        "extent": layer["extent"],
        "category": "ignored",
        "reason": WHITELIST_IGNORED_REASON,
        "transferable": False,
    }


def _should_ignore_by_box(normalized_layer_name: str, normalized_gpkg: str):
    if normalized_layer_name in PROTECTED_TRANSFERABLE_LAYER_NAMES:
        return False

    if normalized_layer_name.startswith("arb_adjunto_"):
        return True

    if normalized_layer_name in IGNORED_EXACT_NAMES:
        return True

    for token in IGNORED_LAYER_TOKENS:
        if token in normalized_layer_name or token in normalized_gpkg:
            return True

    return False


def _is_domain_catalog_layer(layer_name: str, normalized_layer_name: str) -> bool:
    original = str(layer_name or "").strip()
    if not original.startswith("ARB_"):
        return False
    if original.endswith("Tipo"):
        return True
    return normalized_layer_name.startswith("arb_") and normalized_layer_name.endswith("tipo")


def _analyze_single_gpkg(gpkg_path: Path):
    if ogr is not None:
        try:
            return _analyze_gpkg_with_ogr(gpkg_path)
        except Exception:
            log.exception("Fallo el analisis con OGR, se usara fallback SQLite para %s", gpkg_path)
    return _analyze_gpkg_with_sqlite(gpkg_path)


def _analyze_gpkg_with_ogr(gpkg_path: Path):
    dataset = ogr.Open(str(gpkg_path), 0)
    if dataset is None:
        raise ValueError(f"No fue posible abrir el GPKG {gpkg_path.name}.")

    layers = []
    for index in range(dataset.GetLayerCount()):
        layer = dataset.GetLayerByIndex(index)
        if layer is None:
            continue

        layer_definition = layer.GetLayerDefn()
        geometry = "Sin geometria"
        if layer_definition is not None:
            geometry = ogr.GeometryTypeToName(layer_definition.GetGeomType()) or "Desconocido"

        layers.append(
            {
                "name": layer.GetName(),
                "records": int(layer.GetFeatureCount() or 0),
                "geometry": geometry,
                "crs": _format_ogr_crs(layer.GetSpatialRef()),
                "extent": _format_ogr_extent(layer),
            }
        )

    return layers


def _analyze_gpkg_with_sqlite(gpkg_path: Path):
    connection = sqlite3.connect(gpkg_path)
    connection.row_factory = sqlite3.Row

    try:
        contents_rows = connection.execute(
            """
            SELECT
                table_name,
                srs_id,
                min_x,
                min_y,
                max_x,
                max_y
            FROM gpkg_contents
            """
        ).fetchall()

        geometry_rows = connection.execute(
            """
            SELECT
                table_name,
                geometry_type_name
            FROM gpkg_geometry_columns
            """
        ).fetchall()

        srs_rows = connection.execute(
            """
            SELECT
                srs_id,
                organization,
                organization_coordsys_id,
                srs_name
            FROM gpkg_spatial_ref_sys
            """
        ).fetchall()

        geometry_by_table = {
            row["table_name"]: row["geometry_type_name"]
            for row in geometry_rows
        }
        srs_by_id = {row["srs_id"]: row for row in srs_rows}

        layers = []
        for row in contents_rows:
            table_name = row["table_name"]
            layers.append(
                {
                    "name": table_name,
                    "records": _count_records(connection, table_name),
                    "geometry": geometry_by_table.get(table_name, "Sin geometria"),
                    "crs": _format_sqlite_crs(srs_by_id.get(row["srs_id"])),
                    "extent": _format_sqlite_extent(row),
                }
            )

        return layers
    finally:
        connection.close()


def _count_records(connection: sqlite3.Connection, table_name: str):
    escaped_name = table_name.replace('"', '""')
    row = connection.execute(f'SELECT COUNT(*) AS total FROM "{escaped_name}"').fetchone()
    return int(row["total"]) if row else 0


def _format_ogr_crs(spatial_ref):
    if spatial_ref is None:
        return ""

    authority_name = spatial_ref.GetAuthorityName(None)
    authority_code = spatial_ref.GetAuthorityCode(None)
    if authority_name and authority_code:
        return f"{authority_name}:{authority_code}"

    return spatial_ref.GetName() or ""


def _format_ogr_extent(layer):
    try:
        extent = layer.GetExtent(True)
    except Exception:
        return None

    if not extent:
        return None

    return {
        "min_x": extent[0],
        "max_x": extent[1],
        "min_y": extent[2],
        "max_y": extent[3],
    }


def _format_sqlite_crs(srs_row):
    if not srs_row:
        return ""

    organization = srs_row["organization"]
    coordsys_id = srs_row["organization_coordsys_id"]
    if organization and coordsys_id is not None:
        return f"{organization}:{coordsys_id}"

    return srs_row["srs_name"] or ""


def _format_sqlite_extent(row):
    values = (row["min_x"], row["max_x"], row["min_y"], row["max_y"])
    if any(value is None for value in values):
        return None

    return {
        "min_x": row["min_x"],
        "max_x": row["max_x"],
        "min_y": row["min_y"],
        "max_y": row["max_y"],
    }


def _read_metadata(metadata_path: Path | None):
    if not metadata_path:
        return {}

    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        payload = json.loads(metadata_path.read_text(encoding="latin-1"))

    return {
        "project": _pick_metadata_value(payload, "project", "proyecto", "name"),
        "workspace": _pick_metadata_value(payload, "workspace", "namespace"),
        "version": _pick_metadata_value(payload, "version", "project_version"),
        "date": _pick_metadata_value(payload, "date", "fecha", "created", "updated"),
        "user": _pick_metadata_value(payload, "user", "usuario", "owner", "creator"),
    }


def _pick_metadata_value(payload, *keys):
    if not isinstance(payload, dict):
        return ""

    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value

    for value in payload.values():
        if isinstance(value, dict):
            nested = _pick_metadata_value(value, *keys)
            if nested not in (None, ""):
                return nested

    return ""
