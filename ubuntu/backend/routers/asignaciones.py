import os
import re
import tempfile
import logging
from datetime import date, datetime
from typing import Optional, Literal, List
from uuid import UUID

from core.asignaciones import (
    ASIG_SKIP_WORKSPACE,
    ILI2PG_CMD,
    ILI2PG_TIMEOUT_SEC,
    REQUIRED_BASKETS,
    can_access_assignment_model,
)
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Request
from pydantic import BaseModel
from psycopg2.extras import RealDictCursor

from repositories import asignaciones_repo
from routers.auth import get_current_tenant, get_current_user, get_user_role, normalize_role
from services import asignaciones_export as export_service
from services import asignaciones_workspace as workspace_service
from services import asignaciones_workspace_schema as workspace_schema_service
from tenants import TenantContext, app_table, get_tenant_db_connection, main_table

router = APIRouter(prefix="/asignaciones", tags=["asignaciones"])
logger = logging.getLogger(__name__)

AsignacionEstado = Literal[
    "CREANDO_WORKSPACE",
    "EN_TRABAJO",
    "ERROR_WORKSPACE",
    "PENDIENTE_PUBLICACION",
    "SINCRONIZADO",
    "CERRADA",
]


def _user_role_scope(user: Optional[dict]) -> tuple[str, str]:
    role = str(
        (user or {}).get("role")
        or (user or {}).get("rol")
        or (user or {}).get("role_code")
        or ""
    ).strip().lower()
    username = str((user or {}).get("username") or "").strip().lower()
    return role, username


def _require_assignment_access(user: dict, *allowed_roles: str) -> None:
    role = normalize_role(get_user_role(user))
    allowed = {normalize_role(item) for item in allowed_roles if item}
    if allowed and role not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Rol '{role}' sin permisos para esta accion",
        )
    if not can_access_assignment_model(user, role=role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para acceder al modulo de asignaciones.",
        )


def _raise_http_from_export_error(exc: Exception) -> None:
    if isinstance(exc, export_service.ExportServiceError):
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    raise exc

class UsuarioAsignable(BaseModel):
    id_global: int
    username: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    rol: Optional[str] = None


class BuscarPrediosBody(BaseModel):
    numeros: List[str]


class BuscarPrediosResponseItem(BaseModel):
    numero_predial_nacional: str
    existe: bool
    estado: Optional[str] = None
    asignado_a: Optional[str] = None
    asignado_por: Optional[str] = None


class BuscarPrediosResponse(BaseModel):
    total: int
    existen: int
    no_existen: int
    asignados: int
    disponibles: int
    items: List[BuscarPrediosResponseItem]


class AsignarBody(BaseModel):
    numeros: List[str]
    username_destino: str
    titulo: Optional[str] = None
    observaciones: Optional[str] = None
    forzar_reasignacion: bool = False


class AsignacionListadoItem(BaseModel):
    id: int | str
    estado: AsignacionEstado
    fecha_creacion: Optional[str] = None
    coordinador: Optional[str] = None
    usuario_asignado: Optional[str] = None
    titulo: Optional[str] = None
    datasetname_main: Optional[str] = None
    basket_id: Optional[int] = None
    work_datasetname: Optional[str] = None
    observaciones: Optional[str] = None
    total_asignados: Optional[int] = None
    total_eliminados: Optional[int] = None
    total_nuevos: Optional[int] = None
    total_soporte_extra: Optional[int] = None


def _ili2pg_export(tenant: TenantContext, schema: str, basket_ids: List[str], xtf_path: str):
    try:
        return export_service.ili2pg_export(
            tenant,
            schema,
            basket_ids,
            xtf_path,
            ili2pg_cmd=ILI2PG_CMD,
            timeout_sec=ILI2PG_TIMEOUT_SEC,
        )
    except Exception as exc:
        _raise_http_from_export_error(exc)


def _ili2pg_export_dataset(conn, tenant: TenantContext, schema: str, datasetname: str, xtf_path: str):
    try:
        return export_service.ili2pg_export_dataset(
            conn,
            tenant,
            schema,
            datasetname,
            xtf_path,
            ili2pg_cmd=ILI2PG_CMD,
            timeout_sec=ILI2PG_TIMEOUT_SEC,
        )
    except Exception as exc:
        _raise_http_from_export_error(exc)


def _ili2pg_export_asignacion(
    conn,
    tenant: TenantContext,
    schema: str,
    asignacion_id: int,
    datasetname: str,
    xtf_path: str,
):
    try:
        return export_service.ili2pg_export_assignment(
            conn,
            tenant,
            schema=schema,
            asignacion_id=asignacion_id,
            datasetname=datasetname,
            xtf_path=xtf_path,
            required_topics=sorted(REQUIRED_BASKETS),
            ili2pg_cmd=ILI2PG_CMD,
            timeout_sec=ILI2PG_TIMEOUT_SEC,
        )
    except Exception as exc:
        _raise_http_from_export_error(exc)


def _ili2pg_import(conn, tenant, schema: str, datasetname: str, xtf_path: str):
    try:
        return export_service.ili2pg_import(
            conn,
            tenant,
            schema,
            datasetname,
            xtf_path,
            ili2pg_cmd=ILI2PG_CMD,
            timeout_sec=ILI2PG_TIMEOUT_SEC,
        )
    except Exception as exc:
        _raise_http_from_export_error(exc)


def _ogr_export_gdb(
    tenant: TenantContext,
    schema: str,
    datasetname: str,
    gdb_path: str,
    asignacion_id: Optional[int] = None,
) -> None:
    try:
        return export_service.ogr_export_gdb(
            tenant,
            schema,
            datasetname,
            gdb_path,
            asignacion_id=asignacion_id,
        )
    except Exception as exc:
        _raise_http_from_export_error(exc)


def _ogr_export_gpkg(
    tenant: TenantContext,
    schema: str,
    datasetname: str,
    gpkg_path: str,
    asignacion_id: Optional[int] = None,
) -> None:
    try:
        return export_service.ogr_export_gpkg(
            tenant,
            schema,
            datasetname,
            gpkg_path,
            asignacion_id=asignacion_id,
        )
    except Exception as exc:
        _raise_http_from_export_error(exc)


def _format_display_name(first_name: Optional[str], last_name: Optional[str], username: Optional[str]) -> Optional[str]:
    full_name = " ".join(part for part in (first_name, last_name) if part).strip()
    if full_name and username:
        return f"{full_name} ({username})"
    return full_name or username


def _normalize_predios(numeros: List[str]) -> List[str]:
    seen: set[str] = set()
    cleaned: List[str] = []
    for raw in numeros or []:
        num = raw.strip()
        if not num or num in seen:
            continue
        seen.add(num)
        cleaned.append(num)
    return cleaned


def _maybe_int(value) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _ensure_asignacion_tables(conn, tenant: TenantContext) -> None:
    asignaciones_repo.ensure_asignacion_tables(conn, tenant)


def _is_required_basket_name(value: Optional[str]) -> bool:
    if not value:
        return False
    return value.strip() in set(REQUIRED_BASKETS or ())


def _read_datasetname_main_default() -> str:
    value = (os.getenv("ASIG_DATASETNAME_MAIN_DEFAULT", "") or "").strip()
    return value


def _list_baskets_for_dataset(conn, tenant: TenantContext, dataset_id: Optional[int]) -> List[dict]:
    return asignaciones_repo.list_baskets_for_dataset(conn, tenant, dataset_id)


def _log_event(conn, tenant: TenantContext, asignacion_id: int, evento: str, mensaje: Optional[str], usuario: Optional[str]) -> None:
    asignaciones_repo.insert_asignacion_event(conn, tenant, asignacion_id, evento, mensaje, usuario)


def _safe_log_event(conn, tenant: TenantContext, asignacion_id: int, evento: str, mensaje: Optional[str], usuario: Optional[str]) -> None:
    asignaciones_repo.safe_log_event(conn, tenant, asignacion_id, evento, mensaje, usuario)


def _fetch_predios_metadata(conn, tenant: TenantContext, numeros: List[str]) -> List[dict]:
    return asignaciones_repo.fetch_predios_metadata(conn, tenant, numeros)


def _fetch_predios_asignados(conn, tenant: TenantContext, numeros: List[str]) -> List[dict]:
    return asignaciones_repo.fetch_predios_asignados(conn, tenant, numeros)


def _slug_token(value: Optional[str], fallback: str) -> str:
    raw = (value or "").strip().lower()
    clean = re.sub(r"[^a-z0-9_]+", "_", raw)
    clean = re.sub(r"_+", "_", clean).strip("_")
    return clean or fallback


def _build_work_datasetname(
    datasetname_main: Optional[str],
    asignacion_id: int,
    username_destino: Optional[str] = None,
    titulo: Optional[str] = None,
) -> str:
    if username_destino or titulo:
        user_part = _slug_token(username_destino, "usuario")
        title_part = _slug_token(titulo, "lote")
        return f"asig_{user_part}_{title_part}_{asignacion_id}"

    base = datasetname_main or _read_datasetname_main_default() or "dataset"
    clean = _slug_token(base.replace(".", "_").replace("-", "_"), "dataset")
    return f"{clean}_work_{asignacion_id}"


def _update_asignacion_fields(
    conn,
    tenant: TenantContext,
    asignacion_id: int,
    *,
    estado: Optional[str] = None,
    work_datasetname: Optional[str] = None,
    error_msg: Optional[str] = None,
    predios_soporte_extra: Optional[int] = None,
) -> None:
    asignaciones_repo.update_asignacion_fields(
        conn,
        tenant,
        asignacion_id,
        estado=estado,
        work_datasetname=work_datasetname,
        error_msg=error_msg,
        predios_soporte_extra=predios_soporte_extra,
    )


def _cleanup_orphan_assignments(conn, tenant: TenantContext, usuario_log: Optional[str]) -> int:
    """
    Close non-closed assignments that no longer have active predios.
    This prevents stale workspace rows in the tenant work schema from blocking
    new assignments by t_id conflicts.
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        asignacion_table = app_table(tenant, "asignacion")
        asignacion_predio_table = app_table(tenant, "asignacion_predio")
        cur.execute(
            f"""
            SELECT
                a.id,
                a.estado,
                a.work_datasetname
            FROM {asignacion_table} a
            WHERE (
                    a.estado IS DISTINCT FROM 'CERRADA'
                AND NOT EXISTS (
                    SELECT 1
                    FROM {asignacion_predio_table} ap
                    WHERE ap.asignacion_id = a.id
                      AND ap.activo IS DISTINCT FROM FALSE
                )
            ) OR (
                    a.estado = 'CERRADA'
                AND COALESCE(NULLIF(BTRIM(a.work_datasetname), ''), '') <> ''
            )
            FOR UPDATE OF a
            """
        )
        rows = cur.fetchall() or []

    cleaned = 0
    schema_work = tenant.schemas.work
    for row in rows:
        asig_id = _maybe_int(row.get("id"))
        if asig_id is None:
            continue

        estado_actual = (row.get("estado") or "").strip().upper()
        should_close = estado_actual != "CERRADA"
        work_dataset = (row.get("work_datasetname") or "").strip()
        cleanup = {
            "dataset_deleted": 0,
            "rows_deleted": 0,
            "baskets_deleted": 0,
        }
        if work_dataset:
            cleanup = workspace_service.remove_workspace_dataset(
                conn,
                work_dataset,
                schema_work,
            )

        if should_close:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE {asignacion_table}
                    SET estado = 'CERRADA',
                        error_msg = NULL,
                        work_datasetname = CASE
                            WHEN %s THEN NULL
                            ELSE work_datasetname
                        END
                    WHERE id = %s
                    """,
                    (bool(work_dataset), asig_id),
                )
            msg = "Asignacion cerrada automaticamente por no tener predios activos."
        elif work_dataset:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE {asignacion_table}
                    SET work_datasetname = NULL
                    WHERE id = %s
                    """,
                    (asig_id,),
                )
            msg = "Workspace huerfano limpiado en asignacion cerrada."
        else:
            msg = "Asignacion saneada automaticamente."

        if cleanup.get("dataset_deleted"):
            msg += (
                f" Workspace {work_dataset} eliminado "
                f"(filas={cleanup.get('rows_deleted', 0)}, "
                f"baskets={cleanup.get('baskets_deleted', 0)})."
            )
        _log_event(conn, tenant, asig_id, "CERRADA", msg, usuario_log)
        cleaned += 1

    return cleaned


def _procesar_workspace_asignacion(
    connection_manager,
    tenant: TenantContext,
    asignacion_id: int,
    created_by: Optional[str],
    work_datasetname: str,
    datasetname_main: str,
    basket_tids_to_use: List[str],
    export_main_by_dataset: bool,
) -> None:
    try:
        schema_work = tenant.schemas.work
        with connection_manager.connection(tenant) as conn:
            workspace_schema_service.ensure_workspace_schema_ready(
                conn,
                tenant,
                schema_work=schema_work,
            )
            result = workspace_service.build_workspace_for_assignment(
                conn,
                tenant,
                asignacion_id,
                schema_main=tenant.schemas.main,
                schema_work=schema_work,
                datasetname_main=datasetname_main,
                work_datasetname=work_datasetname,
                ili2pg_cmd=ILI2PG_CMD,
                timeout_sec=ILI2PG_TIMEOUT_SEC,
                basket_tids_to_use=basket_tids_to_use,
                export_main_by_dataset=export_main_by_dataset,
            )
        predios_soporte_extra = _maybe_int(result.get("predios_soporte_extra")) or 0
        with connection_manager.connection(tenant) as conn:
            _update_asignacion_fields(
                conn,
                tenant,
                asignacion_id,
                estado="EN_TRABAJO",
                error_msg=None,
                work_datasetname=result.get("dataset_name") or work_datasetname,
                predios_soporte_extra=predios_soporte_extra,
            )
            _safe_log_event(
                conn,
                tenant,
                asignacion_id,
                "WORKSPACE_READY_WARN" if result.get("has_integrity_warnings") else "WORKSPACE_READY",
                (
                    f"Workspace {(result.get('dataset_name') or work_datasetname)} listo en {schema_work}. "
                    f"Modo={result.get('checkout_mode')} "
                    f"predios_dataset={result.get('predios_cargados', 0)} "
                    f"predios_asignacion={result.get('predios_asignacion', 0)} "
                    f"removidos={result.get('removed_predios', 0)} "
                    f"soporte_extra={predios_soporte_extra}."
                ),
                created_by,
            )
            workspace_service.actualizar_predio_ids_desde_workspace(conn, tenant, asignacion_id)
            conn.commit()
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, str) else "Error ejecutando ili2pg"
        with connection_manager.connection(tenant) as conn:
            _update_asignacion_fields(
                conn,
                tenant,
                asignacion_id,
                estado="ERROR_WORKSPACE",
                error_msg=detail,
                work_datasetname=work_datasetname,
            )
            _safe_log_event(conn, tenant, asignacion_id, "ERROR", detail, created_by)
            conn.commit()
    except Exception as e:
        with connection_manager.connection(tenant) as conn:
            _update_asignacion_fields(
                conn,
                tenant,
                asignacion_id,
                estado="ERROR_WORKSPACE",
                error_msg=str(e),
                work_datasetname=work_datasetname,
            )
            _safe_log_event(conn, tenant, asignacion_id, "ERROR", str(e), created_by)
            conn.commit()


@router.get("/usuarios-disponibles", response_model=List[UsuarioAsignable])
def listar_usuarios_disponibles(
    user: dict = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    _require_assignment_access(user, "admin", "coordinador")
    rows = asignaciones_repo.list_usuarios_disponibles(conn, tenant)
    return rows


@router.post("/buscar", response_model=BuscarPrediosResponse)
def buscar_predios(
    body: BuscarPrediosBody,
    user: dict = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    _require_assignment_access(user, "admin", "coordinador")
    numeros = _normalize_predios(body.numeros or [])
    if not numeros:
        raise HTTPException(status_code=400, detail="Debes enviar una lista de numeros.")

    try:
        rows = asignaciones_repo.buscar_predios_estado(conn, tenant, numeros)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error consultando base de datos: {e}")

    existentes = {r.get('numero_predial_nacional') for r in rows}
    lookup = {r.get('numero_predial_nacional'): r for r in rows}

    items: List[dict] = []
    for n in numeros:
        existe = n in existentes
        assigned_info = lookup.get(n) or {}
        asignado_a = assigned_info.get('asignado_a') if existe else None
        asignado_por = assigned_info.get('asignado_por') if existe else None
        estado = 'ASIGNADO' if asignado_a else None
        items.append(
            BuscarPrediosResponseItem(
                numero_predial_nacional=n,
                existe=existe,
                estado=estado,
                asignado_a=asignado_a,
                asignado_por=asignado_por,
            ).dict()
        )

    total = len(numeros)
    existen = sum(1 for it in items if it['existe'])
    asignados = sum(1 for it in items if it['estado'] == 'ASIGNADO')
    disponibles = existen - asignados
    no_existen = total - existen

    return {
        "total": total,
        "existen": existen,
        "no_existen": no_existen,
        "asignados": asignados,
        "disponibles": max(disponibles, 0),
        "items": items,
    }


@router.post("/asignar")
def asignar_predios(
    body: AsignarBody,
    request: Request,
    background: BackgroundTasks,
    user: dict = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    _require_assignment_access(user, "admin", "coordinador")
    numeros = _normalize_predios(body.numeros or [])
    username_destino = (body.username_destino or "").strip()
    if not numeros:
        raise HTTPException(status_code=400, detail="Debes enviar predios para asignar.")
    if not username_destino:
        raise HTTPException(status_code=400, detail="Debes indicar usuario destino.")

    created_by = user.get("username") if isinstance(user, dict) else user
    # Intentamos obtener los ids numericos para enlazar con users del tenant activo.
    created_by_id: Optional[int] = None
    if isinstance(user, dict):
        try:
            if user.get("id_global") is not None:
                created_by_id = int(user["id_global"])
        except (TypeError, ValueError):
            created_by_id = None

    titulo = (body.titulo or "").strip()
    observaciones = (body.observaciones or "").strip() or None

    asignacion_id: Optional[int] = None
    predio_basket_id: Optional[int] = None
    datasetname_main = _read_datasetname_main_default()
    dataset_id_value: Optional[int] = None
    basket_ids_response: List[int] = []
    basket_tids_for_export: List[str] = []
    missing_basket_tids: List[int] = []

    conn.autocommit = False
    asignacion_table = app_table(tenant, "asignacion")
    asignacion_predio_table = app_table(tenant, "asignacion_predio")
    users_table = app_table(tenant, "users")
    try:
        _ensure_asignacion_tables(conn, tenant)
        _cleanup_orphan_assignments(conn, tenant, created_by)

        with conn.cursor(cursor_factory=RealDictCursor) as cur_user:
            cur_user.execute(
                f"""
                SELECT id_global
                FROM {users_table}
                WHERE username = %s
                  AND activo IS TRUE
                """,
                (username_destino,),
            )
            dest_row = cur_user.fetchone()

        if not dest_row or dest_row.get("id_global") is None:
            raise HTTPException(
                status_code=400,
                detail=f"El usuario destino '{username_destino}' no existe o esta inactivo.",
            )

        usuario_destino_id = int(dest_row["id_global"])

        # Si no tenemos id numerico del creador, usamos el de destino solo
        # para no violar restricciones NOT NULL en creado_por_id cuando exista.
        if created_by_id is None:
            created_by_id = usuario_destino_id

        predios_info = _fetch_predios_metadata(conn, tenant, numeros)
        encontrados = {row.get("numero_predial_nacional") for row in predios_info}
        faltantes = [n for n in numeros if n not in encontrados]
        if faltantes:
            raise HTTPException(
                status_code=400,
                detail=f"Los siguientes predios no existen en {tenant.schemas.main}: {', '.join(faltantes)}",
            )

        conflictos = _fetch_predios_asignados(conn, tenant, numeros)
        conflictos_fmt: list[dict] = []
        conflicto_nums: list[str] = []
        conflictos_por_asignacion: dict[int, int] = {}
        for row in conflictos or []:
            num = row.get("numero_predial_nacional")
            asignacion_conf = _maybe_int(row.get("asignacion_id"))
            if num and num not in conflicto_nums:
                conflicto_nums.append(num)
                conflictos_fmt.append(
                    {
                        "numero_predial_nacional": num,
                        "usuario_asignado": row.get("usuario_asignado"),
                        "asignacion_id": asignacion_conf,
                    }
                )
            if asignacion_conf is not None:
                conflictos_por_asignacion[asignacion_conf] = conflictos_por_asignacion.get(asignacion_conf, 0) + 1

        predios_reasignados = len(conflicto_nums)
        if conflictos_fmt and not body.forzar_reasignacion:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Los siguientes predios ya tienen una asignacion activa.",
                    "conflictos": conflictos_fmt,
                },
            )

        if conflictos_fmt and body.forzar_reasignacion:
            conflict_ids = sorted(conflictos_por_asignacion.keys())
            with conn.cursor(cursor_factory=RealDictCursor) as cur_update:
                cur_update.execute(
                    f"""
                    UPDATE {asignacion_predio_table}
                    SET activo = FALSE
                    WHERE numero_predial_nacional = ANY(%s)
                      AND activo IS DISTINCT FROM FALSE
                    """,
                    (conflicto_nums,),
                )

                for asig_id in conflict_ids:
                    total = conflictos_por_asignacion.get(asig_id, 0)
                    cur_update.execute(
                        f"""
                        SELECT work_datasetname
                        FROM {asignacion_table}
                        WHERE id = %s
                        FOR UPDATE
                        """,
                        (asig_id,),
                    )
                    prev_row = cur_update.fetchone() or {}
                    prev_dataset = (prev_row.get("work_datasetname") or "").strip()

                    cur_update.execute(
                        f"""
                        SELECT COUNT(*) AS total
                        FROM {asignacion_predio_table}
                        WHERE asignacion_id = %s
                          AND activo IS DISTINCT FROM FALSE
                        """,
                        (asig_id,),
                    )
                    remaining = int((cur_update.fetchone() or {}).get("total") or 0)

                    if remaining > 0:
                        _log_event(
                            conn,
                            tenant,
                            asig_id,
                            "REASIGNADA",
                            f"{total} predio(s) reasignado(s) por {created_by}.",
                            created_by,
                        )
                        continue

                    cleanup = {
                        "dataset_deleted": 0,
                        "rows_deleted": 0,
                        "baskets_deleted": 0,
                    }
                    if prev_dataset:
                        cleanup = workspace_service.remove_workspace_dataset(
                            conn,
                            prev_dataset,
                            tenant.schemas.work,
                        )

                    cur_update.execute(
                        f"""
                        UPDATE {asignacion_table}
                        SET estado = 'CERRADA',
                            error_msg = NULL,
                            work_datasetname = CASE
                                WHEN %s THEN NULL
                                ELSE work_datasetname
                            END
                        WHERE id = %s
                        """,
                        (bool(prev_dataset), asig_id),
                    )

                    cierre_msg = (
                        f"Asignacion cerrada automaticamente por reasignacion de {total} "
                        f"predio(s) por {created_by}."
                    )
                    if cleanup.get("dataset_deleted"):
                        cierre_msg += (
                            f" Workspace {prev_dataset} eliminado "
                            f"(filas={cleanup.get('rows_deleted', 0)}, "
                            f"baskets={cleanup.get('baskets_deleted', 0)})."
                        )
                    _log_event(conn, tenant, asig_id, "CERRADA", cierre_msg, created_by)
        basket_set = {_maybe_int(row.get("basket_id") or row.get("t_basket")) for row in predios_info}
        basket_set.discard(None)
        if not basket_set:
            raise HTTPException(status_code=400, detail="No fue posible identificar el basket de los predios seleccionados.")
        if len(basket_set) > 1:
            raise HTTPException(status_code=400, detail="Todos los predios deben pertenecer al mismo basket.")
        predio_basket_id = basket_set.pop()

        dataset_ids = {_maybe_int(row.get("dataset_id")) for row in predios_info if row.get("dataset_id") is not None}
        dataset_ids.discard(None)
        if len(dataset_ids) > 1:
            raise HTTPException(status_code=400, detail="Los predios pertenecen a datasets distintos.")
        dataset_id_value = next(iter(dataset_ids)) if dataset_ids else None

        datasetname_db = next((row.get("datasetname_main") for row in predios_info if row.get("datasetname_main")), None)
        datasetname_main = datasetname_db or _read_datasetname_main_default()

        titulo_final = titulo or f"Asignacion manual {len(numeros)} predios"

        lookup = {row.get("numero_predial_nacional"): row for row in predios_info}

        available_baskets = _list_baskets_for_dataset(conn, tenant, dataset_id_value)
        available_map = {
            _maybe_int(row.get("basket_id")): row
            for row in (available_baskets or [])
            if row.get("basket_id") is not None
        }

        required_baskets = [
            bid for bid, row in available_map.items()
            if bid and _is_required_basket_name(row.get("topicname"))
        ]
        base_baskets: List[int] = []
        if predio_basket_id:
            base_baskets.append(predio_basket_id)
        base_baskets.extend(required_baskets)
        basket_ids_final = sorted({bid for bid in base_baskets if bid})

        if not basket_ids_final:
            raise HTTPException(status_code=400, detail="No se pudieron determinar los baskets a clonar. Verifica que el dataset tenga los baskets requeridos.")

        basket_ids_response = basket_ids_final.copy()
        basket_tids_for_export = []
        missing_basket_tids = []
        for bid in basket_ids_final:
            entry = available_map.get(bid)
            identifier = entry.get("basket_tid") if entry else None
            if not identifier:
                for meta in predios_info:
                    meta_bid = _maybe_int(meta.get("basket_id") or meta.get("t_basket"))
                    if meta_bid == bid:
                        identifier = meta.get("basket_tid")
                        if identifier:
                            break
            identifier_str = str(identifier).strip() if identifier is not None else ""
            if identifier_str:
                basket_tids_for_export.append(identifier_str)
            else:
                missing_basket_tids.append(bid)

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                    INSERT INTO {asignacion_table}
                      (usuario_asignado,
                       creado_por,
                       basket_id,
                       datasetname_main,
                       estado,
                       titulo,
                       observaciones,
                       usuario_asignado_id,
                       creado_por_id)
                    VALUES (%s, %s, %s, %s, 'CREANDO_WORKSPACE', %s, %s, %s, %s)
                    RETURNING id
                    """,
                (
                    username_destino,
                    created_by,
                    predio_basket_id,
                    datasetname_main,
                    titulo_final,
                    observaciones,
                    usuario_destino_id,
                    created_by_id,
                ),
            )
            row = cur.fetchone()
            asignacion_id = int(row["id"])

            _log_event(
                conn,
                tenant,
                asignacion_id,
                "CREADA",
                f"Asignacion creada para {username_destino} con {len(numeros)} predios.",
                created_by,
            )

            insert_sql = (
                f"INSERT INTO {asignacion_predio_table}"
                " (asignacion_id, numero_predial_nacional, predio_t_id, activo, creado_por)"
                " VALUES (%s, %s, %s, TRUE, %s)"
            )
            for num in numeros:
                meta = lookup.get(num) or {}
                cur.execute(insert_sql, (asignacion_id, num, meta.get("predio_t_id"), created_by))

            _log_event(
                conn,
                tenant,
                asignacion_id,
                "CREADA",
                f"Detalle creado para {len(numeros)} predios.",
                created_by,
            )

        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"No se pudo crear la asignacion: {e}")

    if asignacion_id is None:
        raise HTTPException(status_code=500, detail="No se pudo determinar el identificador de la asignacion.")

    work_datasetname = _build_work_datasetname(
        datasetname_main,
        asignacion_id,
        username_destino=username_destino,
        titulo=titulo_final,
    )
    _update_asignacion_fields(conn, tenant, asignacion_id, work_datasetname=work_datasetname, error_msg=None)
    conn.commit()

    basket_ids_for_response = basket_ids_response or ([predio_basket_id] if predio_basket_id else [])
    basket_tids_to_use = basket_tids_for_export or []
    export_main_by_dataset = bool(missing_basket_tids) or not basket_tids_to_use

    if ASIG_SKIP_WORKSPACE:
        _update_asignacion_fields(conn, tenant, asignacion_id, estado="EN_TRABAJO", error_msg=None)
        _safe_log_event(
            conn,
            tenant,
            asignacion_id,
            "WORKSPACE_OMITIDO",
            "Workspace omitido por configuracion ASIG_SKIP_WORKSPACE.",
            created_by,
        )
        conn.commit()
        return {
            "id": asignacion_id,
            "basket_id": predio_basket_id,
            "basket_ids": basket_ids_for_response,
            "basket_tids": basket_tids_to_use,
            "datasetname_main": datasetname_main,
            "work_datasetname": work_datasetname,
            "message": "Asignacion creada. Workspace omitido por configuracion.",
            "predios_reasignados": predios_reasignados,
        }

    background.add_task(
        _procesar_workspace_asignacion,
        request.app.state.tenant_connection_manager,
        tenant,
        asignacion_id,
        created_by,
        work_datasetname,
        datasetname_main,
        basket_tids_to_use,
        export_main_by_dataset,
    )
    _safe_log_event(
        conn,
        tenant,
        asignacion_id,
        "WORKSPACE_EN_COLA",
        f"Workspace {work_datasetname} en creacion.",
        created_by,
    )
    conn.commit()

    return {
        "id": asignacion_id,
        "basket_id": predio_basket_id,
        "basket_ids": basket_ids_for_response,
        "basket_tids": basket_tids_to_use,
        "datasetname_main": datasetname_main,
        "work_datasetname": work_datasetname,
        "message": "Asignacion creada. Workspace en creacion.",
        "predios_reasignados": predios_reasignados,
    }


@router.post("/{asignacion_id}/cerrar")
def cerrar_asignacion(
    request: Request,
    asignacion_id: int,
    user: dict = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    _require_assignment_access(user, "admin", "coordinador")
    usuario_log = user.get("username") if isinstance(user, dict) else None
    cierre_estado = "CERRADA"
    work_datasetname_to_cleanup: Optional[str] = None
    workspace_cleanup = {
        "dataset_name": None,
        "rows_deleted": 0,
        "baskets_deleted": 0,
        "dataset_deleted": 0,
    }
    workspace_warning: Optional[str] = None
    predios_liberados = 0
    conn.autocommit = False
    try:
        _ensure_asignacion_tables(conn, tenant)
        asignacion_table = app_table(tenant, "asignacion")
        asignacion_predio_table = app_table(tenant, "asignacion_predio")
        connection_manager = request.app.state.tenant_connection_manager

        def _safe_workspace_cleanup(work_datasetname: str) -> None:
            nonlocal workspace_cleanup, workspace_warning
            if not work_datasetname:
                return
            try:
                with connection_manager.connection(tenant) as cleanup_conn:
                    cleanup_conn.autocommit = False
                    workspace_cleanup = workspace_service.remove_workspace_dataset(
                        cleanup_conn,
                        work_datasetname,
                        tenant.schemas.work,
                    )
                    cleanup_conn.commit()
            except Exception as cleanup_exc:
                workspace_warning = (
                    f"No se pudo limpiar workspace {work_datasetname} en {tenant.schemas.work}: {cleanup_exc}"
                )
                try:
                    with connection_manager.connection(tenant) as log_conn:
                        _safe_log_event(
                            log_conn,
                            tenant,
                            asignacion_id,
                            "WORKSPACE_CLEANUP_ERROR",
                            workspace_warning,
                            usuario_log,
                        )
                        log_conn.commit()
                except Exception:
                    pass

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                    SELECT id, estado, work_datasetname
                    FROM {asignacion_table}
                    WHERE id = %s
                    """,
                (asignacion_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Asignacion no encontrada.")

            estado_actual = (row.get("estado") or "").upper()
            work_datasetname_actual = (row.get("work_datasetname") or "").strip()
            work_datasetname_to_cleanup = work_datasetname_actual

            cur.execute(
                f"""
                    SELECT COUNT(*) AS total
                    FROM {asignacion_predio_table}
                    WHERE asignacion_id = %s
                      AND activo IS DISTINCT FROM FALSE
                    """,
                (asignacion_id,),
            )
            count_row = cur.fetchone()
            predios_liberados = int((count_row or {}).get("total") or 0)

            cur.execute(
                f"""
                    UPDATE {asignacion_predio_table}
                    SET activo = FALSE
                    WHERE asignacion_id = %s
                      AND activo IS DISTINCT FROM FALSE
                    """,
                (asignacion_id,),
            )
            cur.execute(
                f"""
                    UPDATE {asignacion_table}
                    SET estado = 'CERRADA',
                        work_datasetname = NULL,
                        error_msg = NULL
                    WHERE id = %s
                    """,
                (asignacion_id,),
            )
            if (cur.rowcount or 0) == 0:
                raise HTTPException(status_code=404, detail="Asignacion no encontrada.")
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.exception(
            "Error cerrando asignacion id=%s tenant=%s usuario=%s workspace=%s",
            asignacion_id,
            tenant.municipality_code,
            usuario_log,
            workspace_cleanup.get("dataset_name"),
        )
        raise HTTPException(
            status_code=500,
            detail=f"No se pudo cerrar la asignacion ({type(e).__name__}): {e}",
        )

    # Limpiar workspace fuera de la transaccion principal para no bloquear el cierre
    # por FK de tablas auxiliares del modelo de trabajo.
    if work_datasetname_to_cleanup:
        _safe_workspace_cleanup(work_datasetname_to_cleanup)

    return {
        "id": asignacion_id,
        "estado": cierre_estado,
        "predios_liberados": predios_liberados,
        "workspace_rows_deleted": workspace_cleanup.get("rows_deleted", 0),
        "workspace_baskets_deleted": workspace_cleanup.get("baskets_deleted", 0),
        "workspace_dataset_deleted": workspace_cleanup.get("dataset_deleted", 0),
        "warning": workspace_warning,
        "message": (
            "Asignacion cerrada. Workspace pendiente de limpieza."
            if workspace_warning
            else "Asignacion cerrada y predios liberados."
        ),
    }


@router.get("/listado", response_model=List[AsignacionListadoItem])
def listar_asignaciones(
    user: dict = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    _require_assignment_access(user, "admin", "coordinador", "digitalizador", "reconocedor")
    rows = asignaciones_repo.list_asignaciones(conn, tenant)

    role, username = _user_role_scope(user)
    if role in {"digitalizador", "reconocedor"}:
        rows = [
            row
            for row in rows
            if str(row.get("usuario_asignado") or "").strip().lower() == username
        ]

    data: List[AsignacionListadoItem] = []
    for row in rows:
        raw_id = row.get("id")
        asig_id: int | str = raw_id
        if isinstance(raw_id, (bytes, bytearray)):
            asig_id = raw_id.decode("utf-8", errors="ignore")
        elif isinstance(raw_id, UUID):
            asig_id = str(raw_id)

        fecha = row.get("creado_en") or row.get("created_at")
        coordinador_display = _format_display_name(
            row.get("coord_first_name"),
            row.get("coord_last_name"),
            row.get("creado_por"),
        )
        usuario_display = _format_display_name(
            row.get("asignado_first_name"),
            row.get("asignado_last_name"),
            row.get("usuario_asignado"),
        )

        data.append(
            AsignacionListadoItem(
                id=asig_id,
                estado=row.get("estado_resuelto") or row.get("estado", "CREANDO_WORKSPACE"),
                fecha_creacion=(fecha.isoformat() if isinstance(fecha, datetime) else str(fecha)) if fecha else None,
                coordinador=coordinador_display,
                usuario_asignado=usuario_display,
                titulo=row.get("titulo"),
                datasetname_main=row.get("datasetname_main"),
                basket_id=row.get("basket_id"),
                work_datasetname=row.get("work_datasetname"),
                observaciones=row.get("observaciones"),
                total_asignados=_maybe_int(row.get("total_activos")),
                total_eliminados=_maybe_int(row.get("total_inactivos")),
                total_nuevos=_maybe_int(row.get("total_nuevos")),
                total_soporte_extra=_maybe_int(row.get("predios_soporte_extra")),
            )
        )

    return data



