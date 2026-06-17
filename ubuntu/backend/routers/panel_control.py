import logging
from typing import Optional

from fastapi import APIRouter, Depends
from psycopg2.extras import RealDictCursor

from routers.auth import get_current_tenant, require_user, get_user_role, normalize_role
from tenants import TenantContext, get_tenant_db_connection
from repositories.asignaciones_repo import ensure_geoserver_assignment_status_view

router = APIRouter(prefix="/panel-control", tags=["panel_control"])
logger = logging.getLogger(__name__)

_ESTADOS_DISTRIBUCION = (
    "EN_CAMPO",
    "GENERACION_XTF_CAMPO",
    "EN_DIGITALIZACION",
    "CONTROL_CALIDAD_1",
    "CONTROL_CALIDAD_2",
    "DEVUELTO_CAMPO",
    "DEVUELTO_A_CAMPO",
    "DEVUELTO_DIGITALIZACION",
    "DEVUELTO_A_DIGITALIZACION",
    "EN_APROBACION",
    "EN_SINCRONIZACION",
    "SINCRONIZADO",
)

_ESTADOS_EXCLUIDOS = {"CERRADA", "CREANDO_WORKSPACE", "ERROR_WORKSPACE"}


def _initials(first_name: Optional[str], last_name: Optional[str], username: Optional[str]) -> str:
    parts: list[str] = []
    if first_name:
        parts.append(first_name[0].upper())
    if last_name:
        parts.append(last_name[0].upper())
    if not parts and username:
        parts = [c.upper() for c in username[:2] if c.isalpha()]
    return "".join(parts[:2]) or "??"


def _display_name(
    first_name: Optional[str],
    last_name: Optional[str],
    username: Optional[str],
) -> str:
    full = " ".join(p for p in (first_name, last_name) if p).strip()
    return full or username or "Sin nombre"


def _get_excluded_usernames(conn, app_schema: str, user: dict) -> list[str]:
    role = normalize_role(get_user_role(user))
    excluded = []
    if role in {"admin", "soporte"}:
        other_role = "soporte" if role == "admin" else "admin"
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"SELECT username, rol FROM {app_schema}.users")
            for row in cur.fetchall():
                u_name = row.get("username")
                u_rol = row.get("rol")
                if u_name and normalize_role(u_rol) == other_role:
                    excluded.append(u_name)
    return excluded


# ---------------------------------------------------------------------------
# GET /panel-control/resumen-estados
# ---------------------------------------------------------------------------

@router.get("/resumen-estados")
def resumen_estados(
    user: dict = Depends(require_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    """
    Resumen de asignaciones agrupado por estado.
    Alimenta las gráficas de dona del panel de control.
    """
    try:
        ensure_geoserver_assignment_status_view(conn, tenant)
    except Exception as exc:
        logger.warning("No se pudo asegurar la vista de estados para GeoServer: %s", exc)

    app_schema = tenant.schemas.app
    main_schema = tenant.schemas.main

    excluded_usernames = _get_excluded_usernames(conn, app_schema, user)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SET LOCAL lock_timeout = '2s'")
        cur.execute("SET LOCAL statement_timeout = '20s'")

        query_resumen = f"""
            SELECT
                estado::text        AS estado,
                COUNT(*)::int       AS total
            FROM {app_schema}.asignacion a
            WHERE estado::text NOT IN ('CERRADA', 'CREANDO_WORKSPACE', 'ERROR_WORKSPACE')
        """
        params_resumen = []
        if excluded_usernames:
            query_resumen += " AND a.creado_por NOT IN %s"
            params_resumen.append(tuple(excluded_usernames))
        query_resumen += " GROUP BY estado::text ORDER BY estado::text"
        cur.execute(query_resumen, params_resumen)
        rows = cur.fetchall()

        cur.execute(
            f"""
            SELECT COUNT(*)::int AS total
            FROM {main_schema}.arb_predio
            """
        )
        total_predios_row = cur.fetchone() or {}

        query_inicio = f"SELECT MIN(creado_en) AS fecha_inicio FROM {app_schema}.asignacion a"
        params_inicio = []
        if excluded_usernames:
            query_inicio += " WHERE a.creado_por NOT IN %s"
            params_inicio.append(tuple(excluded_usernames))
        cur.execute(query_inicio, params_inicio)
        fecha_inicio_row = cur.fetchone() or {}

        query_act = f"SELECT MAX(actualizado_en) AS ultima_actualizacion FROM {app_schema}.asignacion a"
        params_act = []
        if excluded_usernames:
            query_act += " WHERE a.creado_por NOT IN %s"
            params_act.append(tuple(excluded_usernames))
        cur.execute(query_act, params_act)
        ultima_actualizacion_row = cur.fetchone() or {}

        query_pred_asig = f"""
            SELECT COUNT(DISTINCT ap.numero_predial_nacional)::int AS total
            FROM {app_schema}.asignacion_predio ap
            JOIN {app_schema}.asignacion a
              ON a.id = ap.asignacion_id
            WHERE ap.activo IS DISTINCT FROM FALSE
              AND a.estado::text NOT IN ('CERRADA', 'SINCRONIZADO')
        """
        params_pred_asig = []
        if excluded_usernames:
            query_pred_asig += " AND a.creado_por NOT IN %s"
            params_pred_asig.append(tuple(excluded_usernames))
        cur.execute(query_pred_asig, params_pred_asig)
        predios_asignados_row = cur.fetchone() or {}

        query_pred_sinc = f"""
            SELECT COUNT(DISTINCT ap.numero_predial_nacional)::int AS total
            FROM {app_schema}.asignacion_predio ap
            JOIN {app_schema}.asignacion a
              ON a.id = ap.asignacion_id
            WHERE ap.activo IS DISTINCT FROM FALSE
              AND a.estado::text = 'SINCRONIZADO'
        """
        params_pred_sinc = []
        if excluded_usernames:
            query_pred_sinc += " AND a.creado_por NOT IN %s"
            params_pred_sinc.append(tuple(excluded_usernames))
        cur.execute(query_pred_sinc, params_pred_sinc)
        predios_sincronizados_row = cur.fetchone() or {}

    estados: dict[str, int] = {}
    total = 0
    for row in rows:
        estado = str(row["estado"])
        count = int(row["total"])
        estados[estado] = count
        total += count

    total_predios = int(total_predios_row.get("total") or 0)
    predios_asignados = int(predios_asignados_row.get("total") or 0)
    predios_sincronizados = int(predios_sincronizados_row.get("total") or 0)
    predios_sin_asignar = max(0, total_predios - predios_asignados)
    fecha_inicio = fecha_inicio_row.get("fecha_inicio")
    ultima_actualizacion = ultima_actualizacion_row.get("ultima_actualizacion")

    return {
        "total_asignaciones": total,
        "estados": estados,
        "total_predios": total_predios,
        "predios_asignados": predios_asignados,
        "predios_sincronizados": predios_sincronizados,
        "predios_sin_asignar": predios_sin_asignar,
        "fecha_inicio_proyecto": fecha_inicio.isoformat() if fecha_inicio else None,
        "ultima_actualizacion": ultima_actualizacion.isoformat() if ultima_actualizacion else None,
    }


# ---------------------------------------------------------------------------
# GET /panel-control/coordinadores
# ---------------------------------------------------------------------------

@router.get("/coordinadores")
def coordinadores(
    user: dict = Depends(require_user),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    """
    Datos por coordinador: nro. reconocedores, asignaciones, predios activos,
    distribución por estado (para barras) y lista de reconocedores (para modal).
    """
    app_schema = tenant.schemas.app
    excluded_usernames = _get_excluded_usernames(conn, app_schema, user)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SET LOCAL lock_timeout = '2s'")
        cur.execute("SET LOCAL statement_timeout = '30s'")

        # --- Distribución: asignaciones y predios por coordinador + estado ---
        query_dist = f"""
            SELECT
                u.id_global                                      AS coord_id,
                u.username                                       AS coord_username,
                u.first_name                                     AS coord_first_name,
                u.last_name                                      AS coord_last_name,
                a.estado::text                                   AS estado,
                COUNT(DISTINCT a.id)::int                        AS nro_asignaciones,
                COALESCE(SUM(ap_s.total_activos), 0)::int        AS total_predios,
                MAX(a.actualizado_en)                            AS ultima_actualizacion
            FROM {app_schema}.asignacion a
            JOIN {app_schema}.users u
                ON u.id_global = a.coordinador_asignado_id
            LEFT JOIN LATERAL (
                SELECT COUNT(*) FILTER (WHERE activo IS DISTINCT FROM FALSE) AS total_activos
                FROM {app_schema}.asignacion_predio ap
                WHERE ap.asignacion_id = a.id
            ) ap_s ON TRUE
            WHERE a.estado::text NOT IN ('CERRADA', 'CREANDO_WORKSPACE', 'ERROR_WORKSPACE')
              AND a.coordinador_asignado_id IS NOT NULL
        """
        params_dist = []
        if excluded_usernames:
            query_dist += " AND a.creado_por NOT IN %s"
            params_dist.append(tuple(excluded_usernames))
        query_dist += """
            GROUP BY u.id_global, u.username, u.first_name, u.last_name, a.estado::text
            ORDER BY u.last_name NULLS LAST, u.first_name NULLS LAST, u.username
        """
        cur.execute(query_dist, params_dist)
        dist_rows = cur.fetchall()

        # --- Reconocedores activos por coordinador ---
        query_recs = f"""
            SELECT DISTINCT
                a.coordinador_asignado_id   AS coord_id,
                ru.username                 AS rec_username,
                ru.first_name               AS rec_first_name,
                ru.last_name                AS rec_last_name
            FROM {app_schema}.asignacion a
            JOIN {app_schema}.users ru
                ON ru.username = a.usuario_asignado
            WHERE a.estado::text NOT IN ('CERRADA', 'CREANDO_WORKSPACE', 'ERROR_WORKSPACE')
              AND a.coordinador_asignado_id IS NOT NULL
              AND a.usuario_asignado IS NOT NULL
        """
        params_recs = []
        if excluded_usernames:
            query_recs += " AND a.creado_por NOT IN %s"
            params_recs.append(tuple(excluded_usernames))
        query_recs += " ORDER BY a.coordinador_asignado_id, ru.last_name NULLS LAST, ru.first_name NULLS LAST"
        cur.execute(query_recs, params_recs)
        recs_rows = cur.fetchall()

    # --- Construir diccionario de coordinadores ---
    coords: dict[int, dict] = {}

    for row in dist_rows:
        coord_id = int(row["coord_id"])
        if coord_id not in coords:
            fname = row["coord_first_name"] or ""
            lname = row["coord_last_name"] or ""
            uname = row["coord_username"] or ""
            coords[coord_id] = {
                "id":            coord_id,
                "nombre":        _display_name(fname, lname, uname),
                "username":      uname,
                "iniciales":     _initials(fname, lname, uname),
                "asignaciones":  0,
                "predios":       0,
                "ultima_actualizacion": None,
                "dist": {estado: 0 for estado in _ESTADOS_DISTRIBUCION},
                "recs": [],
            }

        estado = str(row["estado"])
        ultima_actualizacion = row.get("ultima_actualizacion")

        coords[coord_id]["asignaciones"] += int(row["nro_asignaciones"])
        coords[coord_id]["predios"]      += int(row["total_predios"])
        if (
            ultima_actualizacion
            and (
                coords[coord_id]["ultima_actualizacion"] is None
                or ultima_actualizacion > coords[coord_id]["ultima_actualizacion"]
            )
        ):
            coords[coord_id]["ultima_actualizacion"] = ultima_actualizacion

        if estado in coords[coord_id]["dist"]:
            coords[coord_id]["dist"][estado] += int(row["total_predios"])

    # --- Asociar reconocedores ---
    recs_per_coord: dict[int, list] = {}
    for row in recs_rows:
        coord_id = int(row["coord_id"])
        recs_per_coord.setdefault(coord_id, []).append({
            "nombre":   _display_name(row["rec_first_name"], row["rec_last_name"], row["rec_username"]),
            "username": row["rec_username"],
            "iniciales": _initials(row["rec_first_name"], row["rec_last_name"], row["rec_username"]),
        })

    # --- Calcular avance y agregar reconocedores ---
    for coord_id, coord in coords.items():
        coord["recs"] = recs_per_coord.get(coord_id, [])
        coord["reconocedores"] = len(coord["recs"])

        total_p = coord["predios"]
        sinc_p  = coord["dist"].get("SINCRONIZADO", 0)
        coord["avance"] = round((sinc_p / total_p) * 100) if total_p > 0 else 0
        if coord["ultima_actualizacion"]:
            coord["ultima_actualizacion"] = coord["ultima_actualizacion"].isoformat()

    return list(coords.values())
