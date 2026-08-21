from typing import Optional
import logging
import re
import secrets

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from core.asignaciones import ASIG_MODEL_CONTEXT
from repositories import asignaciones_repo
from routers.auth import get_user, get_user_role, normalize_role, check_admin_soporte_isolation
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
    interesados: Optional[list] = None
    visita: Optional[dict] = None


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_identifier(value: str, *, fallback: str) -> str:
    clean = (value or "").strip()
    if _IDENTIFIER_RE.match(clean):
        return clean
    return fallback


def is_valid_csrf(*, user: dict, payload_token: str, header_token: Optional[str]) -> bool:
    session_token = str(user.get("csrf_edit_predio") or "").strip()
    if not session_token:
        # Si no se configuró en la sesión, saltamos la validación para desarrollo
        return True
        
    payload = str(payload_token or "").strip()
    header = str(header_token or "").strip()

    if not payload or not header:
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
def guardar_edicion_predio(
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
        check_admin_soporte_isolation(conn, None, user, payload.asignacion_id)
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

                # Helper to clean numeric strings (e.g. "1.234,56 m2" -> 1234.56)
                def clean_num(val_str: str) -> Optional[float]:
                    if not val_str or not val_str.strip() or val_str.strip() == "----" or val_str.strip() == "---":
                        return None
                    cleaned = re.sub(r"[^\d.,-]", "", val_str).replace(",", ".")
                    try:
                        return float(cleaned)
                    except ValueError:
                        return None

                # Helper to clean integer strings
                def clean_int(val_str: str) -> Optional[int]:
                    if not val_str or not val_str.strip() or val_str.strip() == "----" or val_str.strip() == "---":
                        return None
                    cleaned = re.sub(r"[^\d-]", "", val_str)
                    try:
                        return int(cleaned)
                    except ValueError:
                        return None

                # Helper to resolve domain/lookup display names to IDs
                def resolve_lookup(table_name: str, label_text: str) -> Optional[int]:
                    if not label_text or not label_text.strip() or label_text.strip() == "Selecciona" or label_text.strip() == "Ninguna selección":
                        return None
                    val = label_text.strip()
                    
                    # If value is already a numeric ID, verify it exists in the table and return it directly
                    if val.isdigit():
                        cur.execute(
                            f"SELECT t_id FROM {schema_work}.{table_name} WHERE t_id = %s LIMIT 1",
                            (int(val),),
                        )
                        row = cur.fetchone()
                        if row:
                            return int(row[0])

                    # Try exact match on dispname or ilicode
                    cur.execute(
                        f"""
                        SELECT t_id FROM {schema_work}.{table_name}
                        WHERE BTRIM(dispname) = %s OR BTRIM(ilicode) = %s
                        LIMIT 1
                        """,
                        (val, val),
                    )
                    row = cur.fetchone()
                    if row:
                        return int(row[0])
                    # Fallback to ILIKE match
                    cur.execute(
                        f"""
                        SELECT t_id FROM {schema_work}.{table_name}
                        WHERE dispname ILIKE %s
                        LIMIT 1
                        """,
                        (f"%{val}%",),
                    )
                    row = cur.fetchone()
                    if row:
                        return int(row[0])
                    return None

                # 1. Update text/editable fields in arb_predio
                if "numero_predial_anterior" in payload.campos_editables:
                    val = payload.campos_editables["numero_predial_anterior"].valor
                    if val == "----" or val == "---":
                        val = None
                    cur.execute(
                        f"UPDATE {schema_work}.arb_predio SET numero_predial_anterior = %s WHERE t_id = %s",
                        (val or None, workspace_predio_t_id),
                    )
                    if cur.rowcount:
                        updated_fields.append("numero_predial_anterior")

                if "matricula_inmobiliaria" in payload.campos_editables:
                    val = clean_int(payload.campos_editables["matricula_inmobiliaria"].valor)
                    cur.execute(
                        f"UPDATE {schema_work}.arb_predio SET matricula_inmobiliaria = %s WHERE t_id = %s",
                        (val, workspace_predio_t_id),
                    )
                    if cur.rowcount:
                        updated_fields.append("matricula_inmobiliaria")

                if "codigo_orip" in payload.campos_editables:
                    val = payload.campos_editables["codigo_orip"].valor
                    if val == "----" or val == "---":
                        val = None
                    cur.execute(
                        f"UPDATE {schema_work}.arb_predio SET codigo_orip = %s WHERE t_id = %s",
                        (val or None, workspace_predio_t_id),
                    )
                    if cur.rowcount:
                        updated_fields.append("codigo_orip")

                if "area_registral" in payload.campos_editables:
                    val = clean_num(payload.campos_editables["area_registral"].valor)
                    cur.execute(
                        f"UPDATE {schema_work}.arb_predio SET area_registral_m2 = %s WHERE t_id = %s",
                        (val, workspace_predio_t_id),
                    )
                    if cur.rowcount:
                        updated_fields.append("area_registral_m2")

                if "area_catastral_del_terreno" in payload.campos_editables:
                    val = clean_num(payload.campos_editables["area_catastral_del_terreno"].valor)
                    cur.execute(
                        f"UPDATE {schema_work}.arb_predio SET area_catastral_terreno = %s WHERE t_id = %s",
                        (val, workspace_predio_t_id),
                    )
                    if cur.rowcount:
                        updated_fields.append("area_catastral_terreno")

                if "cabida_y_linderos" in payload.campos_editables:
                    val = payload.campos_editables["cabida_y_linderos"].valor
                    if val == "----" or val == "---":
                        val = None
                    cur.execute(
                        f"UPDATE {schema_work}.arb_predio SET cabida_linderos = %s WHERE t_id = %s",
                        (val or None, workspace_predio_t_id),
                    )
                    if cur.rowcount:
                        updated_fields.append("cabida_linderos")

                if "objervacion_juridica" in payload.campos_editables:
                    val = payload.campos_editables["objervacion_juridica"].valor
                    if val == "----" or val == "---":
                        val = None
                    cur.execute(
                        f"UPDATE {schema_work}.arb_predio SET observacion_juridica = %s WHERE t_id = %s",
                        (val or None, workspace_predio_t_id),
                    )
                    if cur.rowcount:
                        updated_fields.append("observacion_juridica")

                # 2. Update checkboxes in arb_predio
                comodato_val = None
                if "comodato" in payload.checks:
                    comodato_val = bool(payload.checks["comodato"])
                elif "comodatocheck" in payload.checks:
                    comodato_val = bool(payload.checks["comodatocheck"])

                if comodato_val is not None:
                    cur.execute(
                        f"UPDATE {schema_work}.arb_predio SET comodato = %s WHERE t_id = %s",
                        (comodato_val, workspace_predio_t_id),
                    )
                    if cur.rowcount:
                        updated_fields.append("comodato")

                beneficio_val = None
                if "beneficio_comunidades_indigenas" in payload.checks:
                    beneficio_val = bool(payload.checks["beneficio_comunidades_indigenas"])
                elif "beneficiocomunidadesindigenascheck" in payload.checks:
                    beneficio_val = bool(payload.checks["beneficiocomunidadesindigenascheck"])

                if beneficio_val is not None:
                    cur.execute(
                        f"UPDATE {schema_work}.arb_predio SET beneficio_comunidades_indigenas = %s WHERE t_id = %s",
                        (beneficio_val, workspace_predio_t_id),
                    )
                    if cur.rowcount:
                        updated_fields.append("beneficio_comunidades_indigenas")

                # 3. Update dropdowns / lookup fields in arb_predio
                if "condicion_predio" in payload.campos_ocultos:
                    raw_val = payload.campos_ocultos["condicion_predio"]
                    val = resolve_lookup("arb_condicionprediotipo", raw_val)
                    cur.execute(
                        f"UPDATE {schema_work}.arb_predio SET condicion_predio = %s WHERE t_id = %s",
                        (val, workspace_predio_t_id),
                    )
                    if cur.rowcount:
                        updated_fields.append("condicion_predio")

                if "tipo_predio" in payload.campos_ocultos:
                    raw_val = payload.campos_ocultos["tipo_predio"]
                    val = resolve_lookup("arb_prediotipo", raw_val)
                    cur.execute(
                        f"UPDATE {schema_work}.arb_predio SET tipo = %s WHERE t_id = %s",
                        (val, workspace_predio_t_id),
                    )
                    if cur.rowcount:
                        updated_fields.append("tipo")

                if "destinacion_economica" in payload.campos_ocultos:
                    raw_val = payload.campos_ocultos["destinacion_economica"]
                    val = resolve_lookup("arb_destinacioneconomicatipo", raw_val)
                    cur.execute(
                        f"UPDATE {schema_work}.arb_predio SET destinacion_economica = %s WHERE t_id = %s",
                        (val, workspace_predio_t_id),
                    )
                    if cur.rowcount:
                        updated_fields.append("destinacion_economica")

                # 4. Update address type (original logic)
                tipo_direccion = payload.campos_ocultos.get("tipo_direccion_tab3")
                if tipo_direccion:
                    cur.execute(
                        f"UPDATE {schema_work}.arb_direccion SET tipo_direccion = %s WHERE arb_predio_direccion = %s",
                        (tipo_direccion, workspace_predio_t_id),
                    )
                    if cur.rowcount:
                        updated_fields.append("arb_direccion.tipo_direccion")

                # 4b. Update visita and atendioVisita fields in arb_predio
                if payload.visita is not None:
                    vis = payload.visita.get("visita") or {}
                    ate = payload.visita.get("atendioVisita") or {}
                    
                    res_vis_id = resolve_lookup("arb_resultadovisitatipo", vis.get("resultadoVisita"))
                    fec_vis = vis.get("fechaVisitaPredial") or None
                    if fec_vis == "" or fec_vis == "----":
                        fec_vis = None
                    obs_vis = vis.get("observaciones") or None
                    if obs_vis == "Sin datos..." or obs_vis == "----":
                        obs_vis = None
                    con_cal = vis.get("controlCalidad") or None
                    if con_cal == "Sin datos..." or con_cal == "----":
                        con_cal = None
                        
                    cond_pred_id = resolve_lookup("arb_condicionprediotipo", ate.get("condicionPredio"))
                    tipo_doc_id = resolve_lookup("arb_interesadodocumentotipo", ate.get("tipoDocumento"))
                    num_doc = ate.get("numeroDocumento") or None
                    if num_doc == "Sin datos..." or num_doc == "----":
                        num_doc = None
                    corr_elec = ate.get("correoElectronico") or None
                    if corr_elec == "Sin datos..." or corr_elec == "----":
                        corr_elec = None
                    dom_notif = ate.get("domicilioNotificaciones") or None
                    if dom_notif == "Sin datos..." or dom_notif == "----":
                        dom_notif = None
                    aut_notif = bool(ate.get("autorizaNotificaciones"))
                    
                    cur.execute(
                        f"""
                        UPDATE {schema_work}.arb_predio
                        SET resultado_visita = %s,
                            fecha_visita_predial = %s,
                            observaciones = %s,
                            control_calidad = %s,
                            condicion_predio = %s,
                            tipo_documento_quien_atendio = %s,
                            numero_documento_quien_atendio = %s,
                            correo_electronico = %s,
                            domicilio_notificaciones = %s,
                            autoriza_notificaciones = %s
                        WHERE t_id = %s
                        """,
                        (
                            res_vis_id,
                            fec_vis,
                            obs_vis,
                            con_cal,
                            cond_pred_id,
                            tipo_doc_id,
                            num_doc,
                            corr_elec,
                            dom_notif,
                            aut_notif,
                            workspace_predio_t_id
                        )
                    )
                    if cur.rowcount:
                        updated_fields.extend([
                            "resultado_visita", "fecha_visita_predial", "observaciones", "control_calidad",
                            "condicion_predio", "tipo_documento_quien_atendio", "numero_documento_quien_atendio",
                            "correo_electronico", "domicilio_notificaciones", "autoriza_notificaciones"
                        ])

                # 5. Sincronizar interesados (derecho/fuente/interesado)
                if payload.interesados is not None:
                    import uuid
                    # Obtener IDs existentes para este predio
                    cur.execute(
                        f"SELECT t_id FROM {schema_work}.arb_derechointeresadofuente WHERE predio = %s",
                        (workspace_predio_t_id,),
                    )
                    existing_ids = {row[0] for row in cur.fetchall()}
                    retained_ids = set()

                    for item in payload.interesados:
                        id_persona = item.get("idPersona")
                        
                        # Extraer y limpiar campos
                        d_cuota = clean_num(str(item.get("cuotaParticipacion") or ""))
                        d_fecha_inicio = item.get("fechaInicioTendencia") or None
                        if d_fecha_inicio == "" or d_fecha_inicio == "----":
                            d_fecha_inicio = None
                        d_posesion_ancestral = bool(item.get("posesionAncestralTradicional"))
                        d_desc = item.get("descripcion") or None
                        
                        fa_numero = item.get("numeroFuente") or None
                        # Soporte para fechas en sub-objeto o planas
                        fuente_obj = item.get("fuente") or {}
                        if isinstance(fuente_obj, dict):
                            fa_fecha_doc = fuente_obj.get("fechaDocumentoFuente") or item.get("fechaDocumentoFuente")
                            fa_tipo_raw = fuente_obj.get("tipoFuenteAdministrativa") or item.get("tipoFuenteAdministrativa")
                        else:
                            fa_fecha_doc = item.get("fechaDocumentoFuente")
                            fa_tipo_raw = item.get("tipoFuenteAdministrativa")
                        
                        if fa_fecha_doc == "" or fa_fecha_doc == "----":
                            fa_fecha_doc = None
                        fa_ente = item.get("enteEmisor") or None
                        fa_oficina = clean_int(str(item.get("oficinaOrigen") or ""))
                        fa_nombre = item.get("nombreEente") or item.get("nombre") or None
                        fa_ciudad = item.get("ciudadOrigenEnte") or None
                        fa_estado = item.get("estadoDisponibilidad") or None
                        fa_desc = item.get("descripcionFuente") or item.get("descripcionFuenteGeneral") or None
                        
                        i_doc = item.get("numeroDocumento") or None
                        i_primer_nom = item.get("primerNombre") or None
                        i_segundo_nom = item.get("segundoNombre") or None
                        i_primer_ape = item.get("primerApellido") or None
                        i_segundo_ape = item.get("segundoApellido") or None
                        i_razon = item.get("razonSocial") or None
                        i_campesino = bool(item.get("autorreconoceCampesino"))
                        i_etnico = bool(item.get("autorreconoceEtnico"))
                        
                        ic_dep = item.get("departamentoResidencia") or None
                        ic_mun = item.get("municipioResidencia") or None
                        ic_dom = item.get("domicilioResidencia") or None
                        ic_dir = item.get("direccionResidencia") or None
                        ic_tel = clean_num(str(item.get("telefono") or ""))
                        ic_email = item.get("correoElectronico") or None
                        
                        # Resolver tipos usando resolve_lookup
                        d_tipo_id = resolve_lookup("arb_derechotipo", item.get("tipoDerechoSeleccionado")) or 829
                        fa_tipo_id = resolve_lookup("arb_fuenteadministrativatipo", fa_tipo_raw) or 207
                        i_tipo_id = resolve_lookup("arb_interesadotipo", item.get("tipoInteresado")) or 887
                        i_tipo_doc_id = resolve_lookup("arb_interesadodocumentotipo", item.get("tipoDocumento")) or 850
                        i_sexo_id = resolve_lookup("arb_sexotipo", item.get("genero") or item.get("sexo")) or 1031
                        i_grupo_etnico_id = resolve_lookup("arb_grupoetnicotipo", item.get("grupoEtnico"))

                        try:
                            # Debe ser un entero positivo >= 1 para considerarse registro existente
                            # Decimales (Math.random()), negativos o 0 van por INSERT
                            id_val = float(id_persona) if id_persona is not None else 0.0
                            is_existing = id_val >= 1 and float(int(id_val)) == id_val
                        except (ValueError, TypeError):
                            is_existing = False

                        if is_existing:
                            id_persona_int = int(id_val)
                            retained_ids.add(id_persona_int)
                            
                            cur.execute(
                                f"""
                                UPDATE {schema_work}.arb_derechointeresadofuente
                                SET d_tipo = %s, d_cuota_participacion = %s, d_fecha_inicio_tenencia = %s,
                                    d_posesion_ancestral_y_o_tradicional = %s, d_descripcion = %s,
                                    fa_tipo = %s, fa_numero_fuente = %s, fa_fecha_documento_fuente = %s,
                                    fa_ente_emisor = %s, oficina_origen = %s, nombre = %s,
                                    ciudad_origen = %s, estado_disponibilidad = %s, descripcion_fuente = %s,
                                    i_tipo = %s, i_tipo_documento = %s, i_documento_identidad = %s,
                                    i_primer_nombre = %s, i_segundo_nombre = %s, i_primer_apellido = %s,
                                    i_segundo_apellido = %s, i_sexo = %s, i_grupo_etnico = %s,
                                    i_razon_social = %s, i_autorreconocimiento_campesino = %s,
                                    i_autorreconocimiento_etnico = %s, ic_departamento = %s,
                                    ic_municipio = %s, ic_domicilio_notificacion = %s,
                                    ic_direccion_residencia = %s, ic_telefono = %s,
                                    ic_correo_electronico = %s
                                WHERE t_id = %s AND predio = %s
                                """,
                                (
                                    d_tipo_id, d_cuota, d_fecha_inicio, d_posesion_ancestral, d_desc,
                                    fa_tipo_id, fa_numero, fa_fecha_doc, fa_ente, fa_oficina, fa_nombre,
                                    fa_ciudad, fa_estado, fa_desc,
                                    i_tipo_id, i_tipo_doc_id, i_doc,
                                    i_primer_nom, i_segundo_nom, i_primer_ape, i_segundo_ape,
                                    i_sexo_id, i_grupo_etnico_id, i_razon, i_campesino, i_etnico,
                                    ic_dep, ic_mun, ic_dom, ic_dir, ic_tel, ic_email,
                                    id_persona_int, workspace_predio_t_id
                                )
                            )
                        else:
                            # Obtener basket del predio
                            cur.execute(
                                f"SELECT t_basket FROM {schema_work}.arb_predio WHERE t_id = %s",
                                (workspace_predio_t_id,),
                            )
                            row_p = cur.fetchone()
                            t_basket = row_p[0] if row_p else None
                            
                            t_ili_tid = str(uuid.uuid4())
                            cur.execute(
                                f"""
                                INSERT INTO {schema_work}.arb_derechointeresadofuente (
                                    t_basket, t_ili_tid, predio, d_tipo, d_cuota_participacion, d_fecha_inicio_tenencia,
                                    d_posesion_ancestral_y_o_tradicional, d_descripcion,
                                    fa_tipo, fa_numero_fuente, fa_fecha_documento_fuente,
                                    fa_ente_emisor, oficina_origen, nombre,
                                    ciudad_origen, estado_disponibilidad, descripcion_fuente,
                                    i_tipo, i_tipo_documento, i_documento_identidad,
                                    i_primer_nombre, i_segundo_nombre, i_primer_apellido,
                                    i_segundo_apellido, i_sexo, i_grupo_etnico,
                                    i_razon_social, i_autorreconocimiento_campesino,
                                    i_autorreconocimiento_etnico, ic_departamento,
                                    ic_municipio, ic_domicilio_notificacion,
                                    ic_direccion_residencia, ic_telefono,
                                    ic_correo_electronico
                                ) VALUES (
                                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                                )
                                """,
                                (
                                    t_basket, t_ili_tid, workspace_predio_t_id,
                                    d_tipo_id, d_cuota, d_fecha_inicio, d_posesion_ancestral, d_desc,
                                    fa_tipo_id, fa_numero, fa_fecha_doc, fa_ente, fa_oficina, fa_nombre,
                                    fa_ciudad, fa_estado, fa_desc,
                                    i_tipo_id, i_tipo_doc_id, i_doc,
                                    i_primer_nom, i_segundo_nom, i_primer_ape, i_segundo_ape,
                                    i_sexo_id, i_grupo_etnico_id, i_razon, i_campesino, i_etnico,
                                    ic_dep, ic_mun, ic_dom, ic_dir, ic_tel, ic_email
                                )
                            )
                    
                    # Eliminar removidos
                    deleted_ids = existing_ids - retained_ids
                    if deleted_ids:
                        cur.execute(
                            f"DELETE FROM {schema_work}.arb_derechointeresadofuente WHERE t_id = ANY(%s) AND predio = %s",
                            (list(deleted_ids), workspace_predio_t_id),
                        )
                    updated_fields.append("interesados")

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
                logging.exception("[guardar_edicion_predio] Error de base de datos al guardar predio %s: %s", predio_t_id, exc)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Error de base de datos: {exc}",
                )
