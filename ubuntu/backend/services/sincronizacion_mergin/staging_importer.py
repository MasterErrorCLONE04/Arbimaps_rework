from __future__ import annotations

import re
import shutil
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

try:
    from resource.schema.arb_schema import TABLE_SCHEMAS
except Exception:
    TABLE_SCHEMAS = {}
from services.sincronizacion_mergin import zip_analyzer
from services.sincronizacion_mergin.connection import LocalPostgresConnectionService


SAFE_SCHEMA_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
FORBIDDEN_SCHEMAS = {
    "public",
    "information_schema",
    "pg_catalog",
    "pg_toast",
    "pg_temp",
}

connection_service = LocalPostgresConnectionService()

KNOWN_RELATION_FALLBACKS = [
    {
        "source_table": "ARB_Predio",
        "source_field": "estado_fmi",
        "target_table": "ARB_EstadoFMITipo",
        "target_field": "t_id",
        "relation_id": "arb_predio_estado_fmi_fkey",
    },
    {
        "source_table": "ARB_UnidadConstruccion",
        "source_field": "tipo_planta",
        "target_table": "ARB_ConstruccionPlantaTipo",
        "target_field": "t_id",
        "relation_id": "arb_unidadconstruccion_tipo_planta_fkey",
    },
]

TARGET_TABLE_ALIASES = {
    "arb_punto_de_referencia": ["arb_puntoreferencia"],
    "arb_marca_predial": ["arb_marca", "arb_marcapredial"],
    "arb_unidad_de_construccion": ["arb_unidadconstruccion"],
    "arb_terreno_historico": ["arb_terrenohistorico"],
    "arb_derecho_interesado_fuente": ["arb_derechointeresadofuente"],
    "arb_caracteristicas_de_la_unidad_de_construccion": ["arb_caracteristicasunidadconstruccion"],
    "arb_informacion_ph": ["arb_informacionph"],
    "arb_avaluo_valor": ["arb_avaluovalor"],
    "arb_referencia_registral_del_sistema_antiguo_valor": ["arb_referenciaregistralsistemaantiguovalor"],
    "arb_novedad_numero_predial_valor": ["arb_novedadnumeropredialvalor"],
    "arb_novedad_fmi_valor": ["arb_novedadfmivalor"],
}


def import_uploaded_zip_to_staging(
    *,
    zip_file,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    target_schema: str,
    staging_schema: str,
    mode: str,
    replace: bool = False,
):
    filename = (zip_file.filename or "").strip() or "proyecto.zip"
    if not filename.lower().endswith(".zip"):
        raise ValueError("El archivo cargado debe ser un ZIP.")

    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in {"dry_run", "import"}:
        raise ValueError("mode debe ser 'dry_run' o 'import'.")

    target_schema_value = _validate_schema_name(target_schema, field_name="target_schema")
    staging_schema_value = _validate_schema_name(staging_schema, field_name="staging_schema")
    params = connection_service.build_params(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
    )

    warnings = []
    errors = []

    try:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            zip_path = temp_path / filename
            zip_path.write_bytes(zip_file.file.read())

            extract_dir = temp_path / "extracted"
            extract_dir.mkdir(parents=True, exist_ok=True)
            _extract_zip_safely(zip_path, extract_dir)

            gpkg_paths = sorted(
                path for path in extract_dir.rglob("*")
                if path.is_file() and path.suffix.lower() == ".gpkg"
            )
            transfer_plan = _build_transfer_plan(gpkg_paths, extract_dir, warnings)
            project_relations = _discover_project_relations(extract_dir=extract_dir, warnings=warnings)
            db_state = _inspect_database_state(
                params=params,
                target_schema=target_schema_value,
                staging_schema=staging_schema_value,
            )
            transfer_plan["transferable_layers"] = _align_transfer_layers_to_target_tables(
                params=params,
                target_schema=target_schema_value,
                transfer_layers=transfer_plan["transferable_layers"],
                warnings=warnings,
            )
            relation_diagnostic = _build_relation_diagnostic_preview(transfer_plan["transferable_layers"])

            if normalized_mode == "dry_run":
                if not shutil.which("ogr2ogr"):
                    warnings.append(
                        "ogr2ogr no esta disponible en el entorno; el modo import fallaria hasta instalar esa dependencia."
                    )
                return _build_response(
                    mode=normalized_mode,
                    target_schema=target_schema_value,
                    staging_schema=staging_schema_value,
                    created_schema=False,
                    imported_layers=_build_planned_layers(transfer_plan["transferable_layers"]),
                    ignored_layers=transfer_plan["ignored_layers"],
                    missing_layers=transfer_plan["missing_layers"],
                    relation_diagnostic=relation_diagnostic,
                    warnings=warnings,
                    errors=errors,
                    imported_records=0,
                )

            if not transfer_plan["transferable_layers"]:
                raise ValueError("No se encontraron capas transferibles para importar al schema staging.")

            ogr2ogr_path = shutil.which("ogr2ogr")
            if not ogr2ogr_path:
                raise RuntimeError(
                    "ogr2ogr no esta disponible en el entorno. Fase 4 no intentara escribir geometrias manualmente."
                )

            created_schema = _prepare_staging_schema(
                params=params,
                staging_schema=staging_schema_value,
                staging_exists=db_state["staging_schema_exists"],
                replace=replace,
            )
            imported_layers = _run_import(
                ogr2ogr_path=ogr2ogr_path,
                params=params,
                staging_schema=staging_schema_value,
                transfer_layers=transfer_plan["transferable_layers"],
                warnings=warnings,
                errors=errors,
            )
            imported_layers = _enrich_imported_layers(
                params=params,
                staging_schema=staging_schema_value,
                imported_layers=imported_layers,
                warnings=warnings,
            )
            _ensure_staging_reference_keys(
                params=params,
                staging_schema=staging_schema_value,
                imported_layers=imported_layers,
                warnings=warnings,
            )
            _apply_staging_relationships(
                params=params,
                staging_schema=staging_schema_value,
                imported_layers=imported_layers,
                project_relations=project_relations,
                warnings=warnings,
            )
            relation_diagnostic = _build_relation_diagnostic_runtime(
                params=params,
                staging_schema=staging_schema_value,
                imported_layers=imported_layers,
                warnings=warnings,
            )
            imported_records = sum(
                int(item.get("records") or 0)
                for item in imported_layers
                if item.get("status") == "imported"
            )
            return _build_response(
                mode=normalized_mode,
                target_schema=target_schema_value,
                staging_schema=staging_schema_value,
                created_schema=created_schema,
                imported_layers=imported_layers,
                ignored_layers=transfer_plan["ignored_layers"],
                missing_layers=transfer_plan["missing_layers"],
                relation_diagnostic=relation_diagnostic,
                warnings=warnings,
                errors=errors,
                imported_records=imported_records,
            )
    finally:
        zip_file.file.close()


def _validate_schema_name(value: str, *, field_name: str) -> str:
    schema_name = str(value or "").strip()
    if not schema_name:
        raise ValueError(f"{field_name} es obligatorio.")
    if not SAFE_SCHEMA_RE.match(schema_name):
        raise ValueError(f"{field_name} no cumple el patron seguro permitido.")
    if schema_name.lower() in FORBIDDEN_SCHEMAS:
        raise ValueError(f"{field_name} usa un schema prohibido.")
    return schema_name


def _extract_zip_safely(zip_path: Path, extract_dir: Path):
    extract_root = extract_dir.resolve()
    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.infolist():
            member_path = (extract_dir / member.filename).resolve()
            if extract_root not in member_path.parents and member_path != extract_root:
                raise ValueError("El ZIP contiene rutas no validas.")
        archive.extractall(extract_dir)


def _inspect_database_state(*, params, target_schema: str, staging_schema: str) -> dict[str, bool]:
    query = """
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name IN (%s, %s)
    """
    with psycopg2.connect(**params.as_connect_kwargs()) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (target_schema, staging_schema))
            rows = cur.fetchall() or []

    existing = {str(row["schema_name"]).strip() for row in rows if row.get("schema_name")}
    if target_schema not in existing:
        raise ValueError(f"El target_schema '{target_schema}' no existe en la base de datos.")

    return {
        "target_schema_exists": target_schema in existing,
        "staging_schema_exists": staging_schema in existing,
    }


def _build_transfer_plan(gpkg_paths: list[Path], root: Path, warnings: list[str]) -> dict[str, list[dict[str, object]]]:
    transferable_layers = []
    ignored_layers = []
    found_normalized_names = set()

    for gpkg_path in gpkg_paths:
        relative_gpkg = _relative_path(root, gpkg_path)
        for layer in zip_analyzer._analyze_single_gpkg(gpkg_path):
            classified = zip_analyzer._classify_layer(relative_gpkg, layer)
            normalized_layer_name = classified.get("normalized_name")

            if classified.get("category") == "ignored":
                ignored_layers.append(
                    {
                        "name": classified["name"],
                        "gpkg": classified["gpkg"],
                        "records": classified["records"],
                        "geometry": classified["geometry"],
                        "crs": classified["crs"],
                        "extent": classified["extent"],
                        "reason": classified["reason"],
                        "category": "ignored",
                    }
                )
                continue

            if normalized_layer_name in found_normalized_names:
                warnings.append(
                    f"Se detecto una capa duplicada para {classified['expected_display_name']} en {relative_gpkg}; solo se importara la primera coincidencia."
                )
                continue

            found_normalized_names.add(normalized_layer_name)
            transferable_layers.append(
                {
                    "name": classified["name"],
                    "normalized_name": classified["normalized_name"],
                    "expected_display_name": classified["expected_display_name"],
                    "gpkg": classified["gpkg"],
                    "source_path": str(gpkg_path),
                    "records": int(classified["records"] or 0),
                    "geometry": classified["geometry"],
                    "crs": classified["crs"],
                    "extent": classified["extent"],
                    "category": classified["category"],
                }
            )

    transferable_layers.sort(key=_transfer_sort_key)

    missing_layers = [
        definition["display_name"]
        for definition in zip_analyzer.TRANSFERABLE_LAYER_DEFINITIONS
        if definition["normalized_name"] not in found_normalized_names
    ]

    return {
        "transferable_layers": transferable_layers,
        "ignored_layers": ignored_layers,
        "missing_layers": missing_layers,
    }


def _align_transfer_layers_to_target_tables(*, params, target_schema: str, transfer_layers: list[dict[str, object]], warnings: list[str]) -> list[dict[str, object]]:
    target_tables = _fetch_schema_table_names(params=params, schema_name=target_schema)
    target_by_lookup = {_relation_lookup_key(table_name): table_name for table_name in target_tables}
    aligned_layers = []

    for layer in transfer_layers:
        normalized_name = str(layer.get("normalized_name") or "")
        target_table = normalized_name

        if normalized_name in target_tables:
            target_table = normalized_name
        else:
            for candidate in TARGET_TABLE_ALIASES.get(normalized_name, []):
                if candidate in target_tables:
                    target_table = candidate
                    break
            else:
                lookup_key = _relation_lookup_key(normalized_name)
                if lookup_key and lookup_key in target_by_lookup:
                    target_table = target_by_lookup[lookup_key]

        if target_table != normalized_name:
            warnings.append(
                f"{normalized_name}: se importara en staging como '{target_table}' para coincidir con el schema target."
            )

        aligned_layers.append({**layer, "target_table": target_table})

    return aligned_layers


def _fetch_schema_table_names(*, params, schema_name: str) -> set[str]:
    with psycopg2.connect(**params.as_connect_kwargs()) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_type = 'BASE TABLE'
                """,
                (schema_name,),
            )
            return {
                str(row["table_name"])
                for row in (cur.fetchall() or [])
                if row.get("table_name")
            }


def _prepare_staging_schema(*, params, staging_schema: str, staging_exists: bool, replace: bool) -> bool:
    with psycopg2.connect(**params.as_connect_kwargs()) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            if staging_exists:
                if not replace:
                    raise ValueError(
                        f"El staging_schema '{staging_schema}' ya existe. Usa replace=true para recrearlo de forma controlada."
                    )
                cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(staging_schema)))
            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(staging_schema)))
    return True


def _transfer_sort_key(layer: dict[str, object]) -> tuple[int, str, str]:
    priority = {
        "domain_catalog": 0,
        "operational_table": 1,
        "operational_spatial": 2,
    }
    category = str(layer.get("category") or "")
    return (priority.get(category, 99), str(layer.get("gpkg") or ""), str(layer.get("name") or ""))


def _run_import(*, ogr2ogr_path: str, params, staging_schema: str, transfer_layers: list[dict[str, object]], warnings: list[str], errors: list[str]) -> list[dict[str, object]]:
    imported_layers = []
    connection_string = (
        f"PG:host={params.host} port={params.port} dbname={params.database} "
        f"user={params.user} password={params.password}"
    )

    for layer in transfer_layers:
        source_layer_name = str(layer["name"])
        table_name = str(layer.get("target_table") or layer.get("normalized_name") or layer["name"])
        command = [
            ogr2ogr_path,
            "-f",
            "PostgreSQL",
            connection_string,
            str(layer["source_path"]),
            source_layer_name,
            "-nln",
            f"{staging_schema}.{table_name}",
            "-lco",
            "FID=t_id",
            "-overwrite",
        ]
        if str(layer.get("geometry") or "") != "Sin geometria":
            command.extend(["-lco", "GEOMETRY_NAME=geom"])

        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip() or "Sin detalle"
            errors.append(f"{table_name}: ogr2ogr devolvio error. {detail}")
            imported_layers.append(
                {
                    "name": layer["expected_display_name"],
                    "source_name": layer["name"],
                    "table": table_name,
                    "records": 0,
                    "geometry": layer["geometry"],
                    "srid": None,
                    "status": "error",
                    "detail": detail,
                    "category": layer.get("category"),
                }
            )
            continue

        imported_layers.append(
            {
                "name": layer["expected_display_name"],
                "source_name": layer["name"],
                "table": table_name,
                "records": 0,
                "geometry": layer["geometry"],
                "srid": None,
                "status": "imported",
                "category": layer.get("category"),
            }
        )

    if not imported_layers:
        warnings.append("No se encontraron capas transferibles para importar al schema staging.")

    return imported_layers


def _enrich_imported_layers(*, params, staging_schema: str, imported_layers: list[dict[str, object]], warnings: list[str]) -> list[dict[str, object]]:
    successful_tables = [item["table"] for item in imported_layers if item.get("status") == "imported"]
    if not successful_tables:
        return imported_layers

    table_info = _fetch_staging_table_info(
        params=params,
        staging_schema=staging_schema,
        table_names=successful_tables,
        warnings=warnings,
    )
    for item in imported_layers:
        if item.get("status") != "imported":
            continue
        info = table_info.get(item["table"], {})
        item["records"] = int(info.get("records") or 0)
        item["srid"] = info.get("srid")
        if info.get("geometry_type"):
            item["geometry"] = info["geometry_type"]
        if info.get("geometry_column"):
            item["geometry_column"] = info["geometry_column"]
        if info.get("non_null_geometries") is not None:
            item["non_null_geometries"] = int(info["non_null_geometries"] or 0)
            if str(item.get("geometry") or "") != "Sin geometria":
                warnings.append(
                    f"{item['table']}: staging tiene {item['non_null_geometries']}/{item['records']} geometria(s) no nula(s) en {item.get('geometry_column') or 'columna espacial'}."
                )
        if info.get("invalid_geometries") not in (None, 0):
            item["warning"] = f"Se detectaron {info['invalid_geometries']} geometria(s) invalida(s)."
    return imported_layers


def _fetch_staging_table_info(*, params, staging_schema: str, table_names: list[str], warnings: list[str]) -> dict[str, dict[str, object]]:
    result = {}
    with psycopg2.connect(**params.as_connect_kwargs()) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_type = 'BASE TABLE'
                  AND table_name = ANY(%s)
                """,
                (staging_schema, table_names),
            )
            existing_tables = [row["table_name"] for row in (cur.fetchall() or []) if row.get("table_name")]

            geometry_meta = {}
            try:
                cur.execute(
                    """
                    SELECT f_table_name AS table_name, f_geometry_column AS geometry_column, srid, type
                    FROM geometry_columns
                    WHERE f_table_schema = %s
                      AND f_table_name = ANY(%s)
                    """,
                    (staging_schema, existing_tables),
                )
                geometry_meta = {
                    row["table_name"]: row
                    for row in (cur.fetchall() or [])
                    if row.get("table_name")
                }
            except Exception:
                warnings.append(
                    "No fue posible consultar geometry_columns; el reporte de SRID/geometrias puede quedar incompleto."
                )

            for table_name in existing_tables:
                cur.execute(
                    sql.SQL("SELECT COUNT(*) AS total FROM {}.{}").format(
                        sql.Identifier(staging_schema),
                        sql.Identifier(table_name),
                    )
                )
                count_row = cur.fetchone() or {}
                info = {
                    "records": int(count_row.get("total") or 0),
                    "srid": None,
                    "geometry_type": None,
                    "geometry_column": None,
                    "non_null_geometries": None,
                    "invalid_geometries": None,
                }

                geom_info = geometry_meta.get(table_name)
                if geom_info:
                    info["srid"] = geom_info.get("srid")
                    info["geometry_type"] = geom_info.get("type")
                    geometry_column = geom_info.get("geometry_column")
                    info["geometry_column"] = geometry_column
                    if geometry_column:
                        try:
                            cur.execute(
                                sql.SQL(
                                    "SELECT COUNT(*) AS non_null_total, COUNT(*) FILTER (WHERE {} IS NOT NULL AND NOT ST_IsValid({})) AS invalid_total FROM {}.{}"
                                ).format(
                                    sql.Identifier(geometry_column),
                                    sql.Identifier(geometry_column),
                                    sql.Identifier(staging_schema),
                                    sql.Identifier(table_name),
                                )
                            )
                            geometry_row = cur.fetchone() or {}
                            info["non_null_geometries"] = int(geometry_row.get("non_null_total") or 0)
                            info["invalid_geometries"] = int(geometry_row.get("invalid_total") or 0)
                        except Exception:
                            warnings.append(
                                f"No fue posible calcular geometrias de staging para {staging_schema}.{table_name}."
                            )

                result[table_name] = info

    return result


def _build_planned_layers(transfer_layers: list[dict[str, object]]) -> list[dict[str, object]]:
    planned = []
    for layer in transfer_layers:
        planned.append(
            {
                "name": layer["expected_display_name"],
                "source_name": layer["name"],
                "table": str(layer.get("target_table") or layer.get("normalized_name") or layer["name"]),
                "records": int(layer["records"] or 0),
                "geometry": layer["geometry"],
                "srid": _extract_srid(layer["crs"]),
                "status": "planned",
                "category": layer.get("category"),
            }
        )
    return planned


def _extract_srid(crs_value: object):
    text = str(crs_value or "").strip()
    if ":" not in text:
        return None
    try:
        return int(text.rsplit(":", 1)[1])
    except ValueError:
        return None


def _build_relation_diagnostic_preview(transfer_layers: list[dict[str, object]]) -> dict[str, object]:
    imported_tables = _build_imported_table_index(transfer_layers)
    catalog_tables = sorted(
        item["name"]
        for item in imported_tables.values()
        if item.get("category") == "domain_catalog"
    )
    relations = []
    for table_schema in TABLE_SCHEMAS.values():
        source_key = _relation_lookup_key(table_schema.name)
        source_info = imported_tables.get(source_key)
        if not source_info:
            continue
        for relation in table_schema.relations.values():
            target_key = _relation_lookup_key(relation.target_table)
            target_info = imported_tables.get(target_key)
            relations.append(
                {
                    "source_table": source_info["name"],
                    "source_field": relation.field,
                    "target_table": relation.target_table,
                    "target_field": relation.target_field,
                    "status": "ready_for_validation" if target_info else "missing_target_table",
                    "relation_id": relation.relation_id,
                }
            )

    return {
        "mode": "preview",
        "domain_catalog_tables": catalog_tables,
        "domain_catalog_count": len(catalog_tables),
        "relations": relations,
        "summary": {
            "total_relations": len(relations),
            "ready_for_validation": len([item for item in relations if item["status"] == "ready_for_validation"]),
            "missing_target_table": len([item for item in relations if item["status"] == "missing_target_table"]),
        },
    }


def _build_imported_table_index(layers: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    result = {}
    for layer in layers:
        table_name = str(layer.get("table") or layer.get("source_name") or layer.get("name") or "")
        normalized = _relation_lookup_key(table_name)
        if not normalized:
            continue
        result[normalized] = {
            "name": table_name,
            "display_name": layer.get("name") or table_name,
            "category": layer.get("category"),
        }
    return result


def _build_relation_diagnostic_runtime(*, params, staging_schema: str, imported_layers: list[dict[str, object]], warnings: list[str]) -> dict[str, object]:
    imported_tables = _build_imported_table_index(imported_layers)
    table_columns = _fetch_table_columns(params=params, staging_schema=staging_schema)
    existing_fks = _fetch_existing_foreign_keys(params=params, staging_schema=staging_schema, warnings=warnings)
    catalog_tables = sorted(
        item["name"]
        for item in imported_tables.values()
        if item.get("category") == "domain_catalog"
    )

    relations = []
    for table_schema in TABLE_SCHEMAS.values():
        source_key = _relation_lookup_key(table_schema.name)
        source_info = imported_tables.get(source_key)
        if not source_info:
            continue

        source_columns = table_columns.get(source_info["name"], {})
        for relation in table_schema.relations.values():
            target_key = _relation_lookup_key(relation.target_table)
            target_info = imported_tables.get(target_key)
            source_field_key = zip_analyzer.normalize_layer_name(relation.field)
            actual_source_field = source_columns.get(source_field_key)
            if not actual_source_field:
                relations.append(
                    {
                        "source_table": source_info["name"],
                        "source_field": relation.field,
                        "target_table": relation.target_table,
                        "target_field": relation.target_field,
                        "status": "missing_source_column",
                        "relation_id": relation.relation_id,
                    }
                )
                continue
            if not target_info:
                relations.append(
                    {
                        "source_table": source_info["name"],
                        "source_field": actual_source_field,
                        "target_table": relation.target_table,
                        "target_field": relation.target_field,
                        "status": "missing_target_table",
                        "relation_id": relation.relation_id,
                    }
                )
                continue

            orphan_count = _count_orphan_references(
                params=params,
                staging_schema=staging_schema,
                source_table=source_info["name"],
                source_field=actual_source_field,
                target_table=target_info["name"],
                target_field=relation.target_field,
                warnings=warnings,
            )
            fk_status = "present" if (source_info["name"], actual_source_field, target_info["name"], relation.target_field) in existing_fks else "missing"
            if orphan_count is None:
                status = "validation_error"
            else:
                status = "resolved" if orphan_count == 0 else "orphan_values"
            relations.append(
                {
                    "source_table": source_info["name"],
                    "source_field": actual_source_field,
                    "target_table": target_info["name"],
                    "target_field": relation.target_field,
                    "status": status,
                    "relation_id": relation.relation_id,
                    "orphan_count": orphan_count,
                    "foreign_key": fk_status,
                }
            )

    return {
        "mode": "runtime",
        "domain_catalog_tables": catalog_tables,
        "domain_catalog_count": len(catalog_tables),
        "relations": relations,
        "summary": {
            "total_relations": len(relations),
            "resolved": len([item for item in relations if item["status"] == "resolved"]),
            "orphan_values": len([item for item in relations if item["status"] == "orphan_values"]),
            "missing_target_table": len([item for item in relations if item["status"] == "missing_target_table"]),
            "missing_source_column": len([item for item in relations if item["status"] == "missing_source_column"]),
            "foreign_keys_present": len([item for item in relations if item.get("foreign_key") == "present"]),
        },
    }


def _fetch_table_columns(*, params, staging_schema: str) -> dict[str, dict[str, str]]:
    with psycopg2.connect(**params.as_connect_kwargs()) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = %s
                ORDER BY ordinal_position
                """,
                (staging_schema,),
            )
            rows = cur.fetchall() or []

    result = {}
    for row in rows:
        table_name = row["table_name"]
        column_name = row["column_name"]
        result.setdefault(table_name, {})[zip_analyzer.normalize_layer_name(column_name)] = column_name
    return result


def _fetch_existing_foreign_keys(*, params, staging_schema: str, warnings: list[str]) -> set[tuple[str, str, str, str]]:
    try:
        with psycopg2.connect(**params.as_connect_kwargs()) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        tc.table_name AS source_table,
                        kcu.column_name AS source_column,
                        ccu.table_name AS target_table,
                        ccu.column_name AS target_column
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                     AND tc.constraint_schema = kcu.constraint_schema
                    JOIN information_schema.constraint_column_usage ccu
                      ON tc.constraint_name = ccu.constraint_name
                     AND tc.constraint_schema = ccu.constraint_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                      AND tc.table_schema = %s
                    """,
                    (staging_schema,),
                )
                rows = cur.fetchall() or []
    except Exception:
        warnings.append("No fue posible consultar las llaves foraneas existentes del staging.")
        return set()

    return {
        (row["source_table"], row["source_column"], row["target_table"], row["target_column"])
        for row in rows
    }


def _count_orphan_references(*, params, staging_schema: str, source_table: str, source_field: str, target_table: str, target_field: str, warnings: list[str]) -> int | None:
    try:
        with psycopg2.connect(**params.as_connect_kwargs()) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT COUNT(*) AS total
                        FROM {}.{} src
                        LEFT JOIN {}.{} dst
                          ON src.{} = dst.{}
                        WHERE src.{} IS NOT NULL
                          AND dst.{} IS NULL
                        """
                    ).format(
                        sql.Identifier(staging_schema),
                        sql.Identifier(source_table),
                        sql.Identifier(staging_schema),
                        sql.Identifier(target_table),
                        sql.Identifier(source_field),
                        sql.Identifier(target_field),
                        sql.Identifier(source_field),
                        sql.Identifier(target_field),
                    )
                )
                row = cur.fetchone() or {}
                return int(row.get("total") or 0)
    except Exception:
        warnings.append(
            f"No fue posible validar referencias entre {staging_schema}.{source_table}.{source_field} y {staging_schema}.{target_table}.{target_field}."
        )
        return None


def _build_response(*, mode: str, target_schema: str, staging_schema: str, created_schema: bool, imported_layers, ignored_layers, missing_layers, relation_diagnostic, warnings, errors, imported_records: int):
    return {
        "ok": len(errors) == 0,
        "mode": mode,
        "target_schema": target_schema,
        "staging_schema": staging_schema,
        "created_schema": created_schema,
        "imported_layers": imported_layers,
        "ignored_layers": ignored_layers,
        "missing_layers": missing_layers,
        "relation_diagnostic": relation_diagnostic,
        "warnings": warnings,
        "errors": errors,
        "summary": {
            "total_layers": len(imported_layers) + len(ignored_layers) + len(missing_layers),
            "imported_layers": len([item for item in imported_layers if item.get("status") in {"planned", "imported"}]),
            "imported_records": imported_records,
            "ignored_layers": len(ignored_layers),
            "missing_layers": len(missing_layers),
            "domain_catalog_layers": len([item for item in imported_layers if item.get("category") == "domain_catalog"]),
        },
    }


def _relative_path(root: Path, path: Path | None):
    if not path:
        return ""
    return str(path.relative_to(root)).replace("\\", "/")


def _relation_lookup_key(name: str) -> str:
    normalized = zip_analyzer.normalize_layer_name(name)
    collapsed = normalized.replace("_", "")
    for token in ("dela", "del", "de", "la", "los", "las"):
        collapsed = collapsed.replace(token, "")
    return collapsed


def _discover_project_relations(*, extract_dir: Path, warnings: list[str]) -> list[dict[str, str]]:
    project_path = zip_analyzer._find_first_file_by_suffix(extract_dir, ".qgs", ".qgz")
    if not project_path:
        return []

    try:
        root = _read_qgis_project_root(project_path)
    except Exception:
        warnings.append("No fue posible leer las relaciones del proyecto QGIS; se aplicaran solo las relaciones conocidas del modelo.")
        return []

    layer_map = {}
    for maplayer in root.findall('.//maplayer'):
        layer_id = (maplayer.findtext('id') or '').strip()
        datasource = (maplayer.findtext('datasource') or '').strip()
        layername = (maplayer.findtext('layername') or '').strip()
        table_name = _extract_table_name_from_datasource(datasource) or layername
        if layer_id and table_name:
            layer_map[layer_id] = table_name

    relations = []
    for relation in root.findall('.//relations/relation'):
        source_table = layer_map.get((relation.get('referencingLayer') or '').strip())
        target_table = layer_map.get((relation.get('referencedLayer') or '').strip())
        relation_id = (relation.get('id') or '').strip() or None
        if not source_table or not target_table:
            continue
        for field_ref in relation.findall('./fieldRef'):
            source_field = (field_ref.get('referencingField') or '').strip()
            target_field = (field_ref.get('referencedField') or '').strip()
            if not source_field or not target_field:
                continue
            relations.append({
                'source_table': source_table,
                'source_field': source_field,
                'target_table': target_table,
                'target_field': target_field,
                'relation_id': relation_id,
                'origin': 'qgis_project',
            })

    return relations


def _read_qgis_project_root(project_path: Path):
    suffix = project_path.suffix.lower()
    if suffix == '.qgs':
        return ET.fromstring(project_path.read_text(encoding='utf-8', errors='ignore'))

    with zipfile.ZipFile(project_path, 'r') as archive:
        qgs_members = [name for name in archive.namelist() if name.lower().endswith('.qgs')]
        if not qgs_members:
            raise ValueError('El QGZ no contiene un proyecto QGS interno.')
        with archive.open(qgs_members[0], 'r') as handle:
            return ET.fromstring(handle.read())


def _extract_table_name_from_datasource(datasource: str) -> str:
    text = str(datasource or '').strip()
    if not text:
        return ''

    table_match = re.search(r'table="([^"]+)"', text, flags=re.IGNORECASE)
    if table_match:
        return table_match.group(1).strip()

    layer_match = re.search(r'layername=([^|]+)', text, flags=re.IGNORECASE)
    if layer_match:
        return layer_match.group(1).strip().strip('"')

    return ''


def _build_expected_relation_specs(*, imported_layers: list[dict[str, object]], table_columns: dict[str, dict[str, str]], project_relations: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    imported_tables = _build_imported_table_index(imported_layers)
    specs: dict[tuple[str, str, str, str], dict[str, str]] = {}

    def add_spec(source_table: str, source_field: str, target_table: str, target_field: str, relation_id: str | None, origin: str):
        key = (source_table, source_field, target_table, target_field)
        current = specs.get(key)
        candidate = {
            'source_table': source_table,
            'source_field': source_field,
            'target_table': target_table,
            'target_field': target_field,
            'relation_id': relation_id,
            'origin': origin,
        }
        if current is None or (current.get('origin') != 'qgis_project' and origin == 'qgis_project'):
            specs[key] = candidate

    for table_schema in TABLE_SCHEMAS.values():
        source_info = imported_tables.get(_relation_lookup_key(table_schema.name))
        if not source_info:
            continue
        source_columns = table_columns.get(source_info['name'], {})
        for relation in table_schema.relations.values():
            target_info = imported_tables.get(_relation_lookup_key(relation.target_table))
            if not target_info:
                continue
            target_columns = table_columns.get(target_info['name'], {})
            actual_source_field = source_columns.get(zip_analyzer.normalize_layer_name(relation.field))
            actual_target_field = target_columns.get(zip_analyzer.normalize_layer_name(relation.target_field))
            if actual_source_field and actual_target_field:
                add_spec(source_info['name'], actual_source_field, target_info['name'], actual_target_field, relation.relation_id, 'arb_schema')

    basket_info = imported_tables.get(_relation_lookup_key('T_ILI2DB_BASKET'))
    if basket_info:
        basket_columns = table_columns.get(basket_info['name'], {})
        basket_target_field = basket_columns.get(zip_analyzer.normalize_layer_name('t_id'))
        if basket_target_field:
            for layer in imported_layers:
                source_table = str(layer.get('table') or layer.get('source_name') or layer.get('name') or '')
                if not source_table or source_table == basket_info['name']:
                    continue
                source_columns = table_columns.get(source_table, {})
                actual_source_field = source_columns.get(zip_analyzer.normalize_layer_name('t_basket'))
                if actual_source_field:
                    add_spec(source_table, actual_source_field, basket_info['name'], basket_target_field, None, 'ili2db_basket')

        dataset_info = imported_tables.get(_relation_lookup_key('T_ILI2DB_DATASET'))
        if dataset_info:
            dataset_columns = table_columns.get(dataset_info['name'], {})
            actual_source_field = basket_columns.get(zip_analyzer.normalize_layer_name('dataset'))
            actual_target_field = dataset_columns.get(zip_analyzer.normalize_layer_name('t_id'))
            if actual_source_field and actual_target_field:
                add_spec(basket_info['name'], actual_source_field, dataset_info['name'], actual_target_field, None, 'ili2db_dataset')

    for fallback in KNOWN_RELATION_FALLBACKS:
        source_info = imported_tables.get(_relation_lookup_key(fallback['source_table']))
        target_info = imported_tables.get(_relation_lookup_key(fallback['target_table']))
        if not source_info or not target_info:
            continue
        source_columns = table_columns.get(source_info['name'], {})
        target_columns = table_columns.get(target_info['name'], {})
        actual_source_field = source_columns.get(zip_analyzer.normalize_layer_name(fallback['source_field']))
        actual_target_field = target_columns.get(zip_analyzer.normalize_layer_name(fallback['target_field']))
        if actual_source_field and actual_target_field:
            add_spec(
                source_info['name'],
                actual_source_field,
                target_info['name'],
                actual_target_field,
                fallback.get('relation_id'),
                'known_fallback',
            )

    for relation in project_relations or []:
        source_info = imported_tables.get(_relation_lookup_key(relation['source_table']))
        target_info = imported_tables.get(_relation_lookup_key(relation['target_table']))
        if not source_info or not target_info:
            continue
        source_columns = table_columns.get(source_info['name'], {})
        target_columns = table_columns.get(target_info['name'], {})
        actual_source_field = source_columns.get(zip_analyzer.normalize_layer_name(relation['source_field']))
        actual_target_field = target_columns.get(zip_analyzer.normalize_layer_name(relation['target_field']))
        if actual_source_field and actual_target_field:
            add_spec(source_info['name'], actual_source_field, target_info['name'], actual_target_field, relation.get('relation_id'), 'qgis_project')

    return list(specs.values())


def _apply_staging_relationships(*, params, staging_schema: str, imported_layers: list[dict[str, object]], project_relations: list[dict[str, str]], warnings: list[str]) -> dict[str, int]:
    table_columns = _fetch_table_columns(params=params, staging_schema=staging_schema)
    existing_fks = _fetch_existing_foreign_keys(params=params, staging_schema=staging_schema, warnings=warnings)
    relation_specs = _build_expected_relation_specs(
        imported_layers=imported_layers,
        table_columns=table_columns,
        project_relations=project_relations,
    )

    if not relation_specs:
        return {'created': 0, 'created_not_valid': 0, 'existing': 0, 'failed': 0}

    _ensure_relation_target_keys(
        params=params,
        staging_schema=staging_schema,
        relation_specs=relation_specs,
        warnings=warnings,
    )

    created = 0
    created_not_valid = 0
    existing = 0
    failed = 0

    with psycopg2.connect(**params.as_connect_kwargs()) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            for spec in relation_specs:
                fk_key = (spec['source_table'], spec['source_field'], spec['target_table'], spec['target_field'])
                if fk_key in existing_fks:
                    existing += 1
                    continue

                orphan_count = _count_orphan_references(
                    params=params,
                    staging_schema=staging_schema,
                    source_table=spec['source_table'],
                    source_field=spec['source_field'],
                    target_table=spec['target_table'],
                    target_field=spec['target_field'],
                    warnings=warnings,
                )
                constraint_name = _build_fk_constraint_name(spec)
                not_valid_sql = sql.SQL(' NOT VALID') if orphan_count not in (None, 0) else sql.SQL('')
                statement = sql.SQL(
                    'ALTER TABLE {}.{} ADD CONSTRAINT {} FOREIGN KEY ({}) REFERENCES {}.{} ({}){}'
                ).format(
                    sql.Identifier(staging_schema),
                    sql.Identifier(spec['source_table']),
                    sql.Identifier(constraint_name),
                    sql.Identifier(spec['source_field']),
                    sql.Identifier(staging_schema),
                    sql.Identifier(spec['target_table']),
                    sql.Identifier(spec['target_field']),
                    not_valid_sql,
                )

                try:
                    cur.execute(statement)
                    existing_fks.add(fk_key)
                    if orphan_count not in (None, 0):
                        created_not_valid += 1
                    else:
                        created += 1
                except Exception as exc:
                    failed += 1
                    conn.rollback()
                    warnings.append(
                        f"No fue posible crear la relacion {spec['source_table']}.{spec['source_field']} -> {spec['target_table']}.{spec['target_field']}: {exc}"
                    )

    if created or created_not_valid:
        warnings.append(
            f"Se materializaron {created + created_not_valid} relacion(es) en el staging ({created} validas, {created_not_valid} NOT VALID)."
        )

    return {'created': created, 'created_not_valid': created_not_valid, 'existing': existing, 'failed': failed}


def _build_fk_constraint_name(spec: dict[str, str]) -> str:
    base = spec.get('relation_id') or f"{spec['source_table']}_{spec['source_field']}_{spec['target_table']}_fkey"
    normalized = re.sub(r'[^a-zA-Z0-9_]+', '_', base).strip('_').lower() or 'fk_rel'
    if len(normalized) <= 63:
        return normalized
    suffix = abs(hash((spec['source_table'], spec['source_field'], spec['target_table'], spec['target_field']))) % 1000000
    return f"{normalized[:56]}_{suffix}"


def _ensure_staging_reference_keys(*, params, staging_schema: str, imported_layers: list[dict[str, object]], warnings: list[str]) -> dict[str, int]:
    imported_tables = sorted(
        {
            str(layer.get('table') or '').strip()
            for layer in imported_layers
            if layer.get('status') == 'imported' and str(layer.get('table') or '').strip()
        }
    )
    if not imported_tables:
        return {'created': 0, 'existing': 0, 'skipped': 0, 'failed': 0}

    created = 0
    existing = 0
    skipped = 0
    failed = 0

    with psycopg2.connect(**params.as_connect_kwargs()) as conn:
        conn.autocommit = True
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            for table_name in imported_tables:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = %s
                      AND table_name = %s
                      AND column_name = 't_id'
                    """,
                    (staging_schema, table_name),
                )
                if not cur.fetchone():
                    skipped += 1
                    continue

                cur.execute(
                    """
                    SELECT 1
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                     AND tc.constraint_schema = kcu.constraint_schema
                    WHERE tc.table_schema = %s
                      AND tc.table_name = %s
                      AND tc.constraint_type IN ('PRIMARY KEY', 'UNIQUE')
                      AND kcu.column_name = 't_id'
                    LIMIT 1
                    """,
                    (staging_schema, table_name),
                )
                if cur.fetchone():
                    existing += 1
                    continue

                cur.execute(
                    sql.SQL(
                        "SELECT COUNT(*) AS total, COUNT(DISTINCT t_id) AS distinct_total, COUNT(*) FILTER (WHERE t_id IS NULL) AS null_total FROM {}.{}"
                    ).format(
                        sql.Identifier(staging_schema),
                        sql.Identifier(table_name),
                    )
                )
                stats = cur.fetchone() or {}
                total = int(stats.get('total') or 0)
                distinct_total = int(stats.get('distinct_total') or 0)
                null_total = int(stats.get('null_total') or 0)
                if null_total > 0 or distinct_total != total:
                    skipped += 1
                    warnings.append(
                        f"No se pudo asegurar clave unica en {staging_schema}.{table_name}.t_id porque tiene {null_total} nulos y {total - distinct_total} duplicados."
                    )
                    continue

                constraint_name = _build_refkey_constraint_name(table_name)
                try:
                    cur.execute(
                        sql.SQL('ALTER TABLE {}.{} ADD CONSTRAINT {} UNIQUE ({})').format(
                            sql.Identifier(staging_schema),
                            sql.Identifier(table_name),
                            sql.Identifier(constraint_name),
                            sql.Identifier('t_id'),
                        )
                    )
                    created += 1
                except Exception as exc:
                    failed += 1
                    warnings.append(
                        f"No fue posible crear la clave unica para {staging_schema}.{table_name}.t_id: {exc}"
                    )

    if created:
        warnings.append(f"Se aseguraron {created} clave(s) unicas sobre t_id en el staging antes de crear relaciones.")

    return {'created': created, 'existing': existing, 'skipped': skipped, 'failed': failed}


def _build_refkey_constraint_name(table_name: str) -> str:
    base = re.sub(r'[^a-zA-Z0-9_]+', '_', f'{table_name}_t_id_key').strip('_').lower() or 't_id_key'
    if len(base) <= 63:
        return base
    suffix = abs(hash(table_name)) % 1000000
    return f"{base[:56]}_{suffix}"



def _ensure_relation_target_keys(*, params, staging_schema: str, relation_specs: list[dict[str, str]], warnings: list[str]) -> dict[str, int]:
    targets = sorted(
        {
            (spec['target_table'], spec['target_field'])
            for spec in relation_specs
            if str(spec.get('target_table') or '').strip() and str(spec.get('target_field') or '').strip()
        }
    )
    if not targets:
        return {'created': 0, 'existing': 0, 'skipped': 0, 'failed': 0}

    created = 0
    existing = 0
    skipped = 0
    failed = 0

    with psycopg2.connect(**params.as_connect_kwargs()) as conn:
        conn.autocommit = True
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            for table_name, column_name in targets:
                cur.execute(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = %s
                      AND table_name = %s
                      AND column_name = %s
                    LIMIT 1
                    """,
                    (staging_schema, table_name, column_name),
                )
                if not cur.fetchone():
                    skipped += 1
                    continue

                cur.execute(
                    """
                    SELECT 1
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                     AND tc.constraint_schema = kcu.constraint_schema
                    WHERE tc.table_schema = %s
                      AND tc.table_name = %s
                      AND tc.constraint_type IN ('PRIMARY KEY', 'UNIQUE')
                      AND tc.constraint_name IN (
                          SELECT kcu2.constraint_name
                          FROM information_schema.key_column_usage kcu2
                          WHERE kcu2.constraint_schema = tc.constraint_schema
                            AND kcu2.table_name = tc.table_name
                          GROUP BY kcu2.constraint_name
                          HAVING COUNT(*) = 1
                      )
                      AND kcu.column_name = %s
                    LIMIT 1
                    """,
                    (staging_schema, table_name, column_name),
                )
                if cur.fetchone():
                    existing += 1
                    continue

                cur.execute(
                    sql.SQL(
                        'SELECT COUNT(*) AS total, COUNT(DISTINCT {}) AS distinct_total, COUNT(*) FILTER (WHERE {} IS NULL) AS null_total FROM {}.{}'
                    ).format(
                        sql.Identifier(column_name),
                        sql.Identifier(column_name),
                        sql.Identifier(staging_schema),
                        sql.Identifier(table_name),
                    )
                )
                stats = cur.fetchone() or {}
                total = int(stats.get('total') or 0)
                distinct_total = int(stats.get('distinct_total') or 0)
                null_total = int(stats.get('null_total') or 0)
                if null_total > 0 or distinct_total != total:
                    skipped += 1
                    warnings.append(
                        f"No se pudo asegurar clave unica en {staging_schema}.{table_name}.{column_name} porque tiene {null_total} nulos y {total - distinct_total} duplicados."
                    )
                    continue

                constraint_name = _build_refkey_constraint_name(f'{table_name}_{column_name}')
                try:
                    cur.execute(
                        sql.SQL('ALTER TABLE {}.{} ADD CONSTRAINT {} UNIQUE ({})').format(
                            sql.Identifier(staging_schema),
                            sql.Identifier(table_name),
                            sql.Identifier(constraint_name),
                            sql.Identifier(column_name),
                        )
                    )
                    created += 1
                except Exception as exc:
                    failed += 1
                    conn.rollback()
                    warnings.append(
                        f"No fue posible crear la clave unica para {staging_schema}.{table_name}.{column_name}: {exc}"
                    )

    if created:
        warnings.append(f"Se aseguraron {created} clave(s) unicas adicionales en columnas destino de relaciones.")

    return {'created': created, 'existing': existing, 'skipped': skipped, 'failed': failed}
