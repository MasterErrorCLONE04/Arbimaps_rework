from typing import Optional
import re
import secrets

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from core.asignaciones import ASIG_MODEL_CONTEXT
from repositories import asignaciones_repo
from routers.auth import get_user, get_user_role, normalize_role
from routers.db import db_conn

router = APIRouter(prefix="/predios", tags=["Edicion Predios"])


class CampoEditableModel(BaseModel):
    etiqueta: str
    valor: str


class EdicionPredioPayload(BaseModel):
    predio_id: int = Field(..., gt=0)
    asignacion_id: int = Field(..., gt=0)
    csrf_token: str = Field(...)
    campos_editables: dict[str, CampoEditableModel]
    campos_ocultos: dict
    checks: dict
    archivos: dict


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_identifier(value: str, *, fallback: str) -> str:
    clean = (value or "").strip()
    if _IDENTIFIER_RE.match(clean):
        return clean
    return fallback


def is_valid_csrf(*, user: dict, payload_token: str, header_token: Optional[str]) -> bool:
    session_token = str(user.get("csrf_edit_predio") or "").strip()
    payload = str(payload_token or "").strip()
    header = str(header_token or "").strip()

    if not session_token or not payload or not header:
        return False
    if len(session_token) < 16:
        return False

    return secrets.compare_digest(session_token, payload) and secrets.compare_digest(session_token, header)


def _safe_log_update_event(
    asignacion_id: int,
    predio_t_id: int,
    usuario: Optional[str],
    updated_fields: list[str],
) -> None:
    if updated_fields:
        fields_text = ", ".join(updated_fields)
        mensaje = f"Predio {predio_t_id} actualizado. Campos aplicados: {fields_text}."
    else:
        mensaje = f"Predio {predio_t_id} guardado sin cambios persistidos."
    try:
        asignaciones_repo.safe_log_event(
            asignacion_id,
            "EDICION_PREDIO_GUARDADA",
            mensaje,
            usuario,
        )
    except Exception:
        # El log no debe tumbar la edicion.
        pass


@router.put("/{predio_t_id}")
async def guardar_edicion_predio(
    predio_t_id: int,
    payload: EdicionPredioPayload,
    request: Request,
    csrf_header: Optional[str] = Header(default=None, alias="X-CSRF-Token"),
):
    user = get_user(request)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")

    if payload.predio_id != predio_t_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inconsistencia de predio_id: URL y payload no coinciden.",
        )

    if not is_valid_csrf(user=user, payload_token=payload.csrf_token, header_token=csrf_header):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token invalido.")

    rol = normalize_role(get_user_role(user))
    if rol not in ["admin", "coordinador", "digitalizador"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Rol no autorizado para edicion.")

    schema_work = _safe_identifier(
        (ASIG_MODEL_CONTEXT.schema_work or "b_asignaciones_arb").strip(),
        fallback="b_asignaciones_arb",
    )
    predio_table = _safe_identifier(
        (ASIG_MODEL_CONTEXT.predio_table or "arb_predio").strip(),
        fallback="arb_predio",
    )
    predio_numero_field = _safe_identifier(
        (ASIG_MODEL_CONTEXT.predio_numero_field or "numero_predial").strip(),
        fallback="numero_predial",
    )

    with db_conn() as conn:
        with conn.cursor() as cur:
            if rol == "digitalizador":
                cur.execute(
                    "SELECT usuario_asignado FROM arbimaps_app.asignacion WHERE id = %s",
                    (payload.asignacion_id,),
                )
                asignacion = cur.fetchone()
                usuario_asignado = str((asignacion or [None])[0] or "").strip().lower()
                username = str(user.get("username") or "").strip().lower()
                if not asignacion or usuario_asignado != username:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="La asignacion no le pertenece.",
                    )

            cur.execute(
                """
                SELECT
                    ap.numero_predial_nacional,
                    a.work_datasetname
                FROM arbimaps_app.asignacion_predio ap
                JOIN arbimaps_app.asignacion a
                  ON a.id = ap.asignacion_id
                WHERE ap.predio_t_id = %s
                  AND ap.asignacion_id = %s
                  AND ap.activo = TRUE
                LIMIT 1
                """,
                (predio_t_id, payload.asignacion_id),
            )
            asignacion_predio = cur.fetchone()
            if not asignacion_predio:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="El predio no existe en la asignacion.",
                )
            numero_predial_nacional = str((asignacion_predio or [None, None])[0] or "").strip()
            work_datasetname = str((asignacion_predio or [None, None])[1] or "").strip()

            workspace_predio_t_id: Optional[int] = None
            if numero_predial_nacional and work_datasetname:
                cur.execute(
                    f"""
                    SELECT p.t_id
                    FROM {schema_work}.{predio_table} p
                    JOIN {schema_work}.t_ili2db_basket b
                      ON b.t_id = p.t_basket
                    JOIN {schema_work}.t_ili2db_dataset d
                      ON d.t_id = b.dataset
                    WHERE d.datasetname = %s
                      AND BTRIM(p.{predio_numero_field}::text) = BTRIM(%s::text)
                    ORDER BY p.t_id DESC
                    LIMIT 1
                    """,
                    (work_datasetname, numero_predial_nacional),
                )
                row = cur.fetchone()
                if row and row[0] is not None:
                    workspace_predio_t_id = int(row[0])

            if workspace_predio_t_id is None and numero_predial_nacional:
                cur.execute(
                    f"""
                    SELECT p.t_id
                    FROM {schema_work}.{predio_table} p
                    WHERE BTRIM(p.{predio_numero_field}::text) = BTRIM(%s::text)
                    ORDER BY p.t_id DESC
                    LIMIT 1
                    """,
                    (numero_predial_nacional,),
                )
                row = cur.fetchone()
                if row and row[0] is not None:
                    workspace_predio_t_id = int(row[0])

            if workspace_predio_t_id is None:
                cur.execute(
                    f"SELECT t_id FROM {schema_work}.{predio_table} WHERE t_id = %s LIMIT 1",
                    (predio_t_id,),
                )
                row = cur.fetchone()
                if row and row[0] is not None:
                    workspace_predio_t_id = int(row[0])

            if workspace_predio_t_id is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No se encontro el predio en la canasta de trabajo para persistir cambios.",
                )

            try:
                updated_fields: list[str] = []

                area_catastral = payload.campos_editables.get("area_catastral_del_terreno")
                if area_catastral and area_catastral.valor:
                    cur.execute(
                        f"UPDATE {schema_work}.arb_predio SET area_catastral_terreno = %s WHERE t_id = %s",
                        (area_catastral.valor, workspace_predio_t_id),
                    )
                    if cur.rowcount:
                        updated_fields.append("arb_predio.area_catastral_terreno")

                tipo_direccion = payload.campos_ocultos.get("tipo_direccion_tab3")
                if tipo_direccion:
                    cur.execute(
                        f"UPDATE {schema_work}.arb_direccion SET tipo_direccion = %s WHERE arb_predio_direccion = %s",
                        (tipo_direccion, workspace_predio_t_id),
                    )
                    if cur.rowcount:
                        updated_fields.append("arb_direccion.tipo_direccion")

                conn.commit()
                _safe_log_update_event(
                    payload.asignacion_id,
                    predio_t_id,
                    str(user.get("username") or "").strip() or None,
                    updated_fields,
                )
                return {"status": "success", "message": "Predio y relaciones actualizados."}
            except Exception as exc:
                conn.rollback()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Error de base de datos: {exc}",
                )
