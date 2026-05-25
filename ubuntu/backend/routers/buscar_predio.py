import logging
import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from psycopg2.extras import RealDictCursor

from routers.auth import get_current_tenant, get_current_user
from tenants import TenantContext, get_tenant_db_connection

logger = logging.getLogger(__name__)
router = APIRouter(prefix="", tags=["buscar_predio"])

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validated_identifier(name: str) -> str:
    value = (name or "").strip()
    if not IDENT_RE.match(value):
        raise HTTPException(status_code=500, detail="Identificador tenant invalido.")
    return value


def _schema_name(tenant: TenantContext) -> str:
    return _validated_identifier(tenant.schemas.main)


def _qualified_table(tenant: TenantContext, table_name: str) -> str:
    return f"{_schema_name(tenant)}.{_validated_identifier(table_name)}"


def _quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _rollback_safely(conn) -> None:
    try:
        conn.rollback()
    except Exception:
        pass


def _execute_fetchone(conn, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    except Exception as exc:
        _rollback_safely(conn)
        raise exc


def _execute_fetchall(conn, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    except Exception as exc:
        _rollback_safely(conn)
        raise exc


def _table_exists(cur, schema: str, table_name: str) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL AS ok;", (f"{schema}.{table_name}",))
    row = cur.fetchone() or {}
    return bool(row.get("ok"))


def _table_columns(cur, schema: str, table_name: str) -> set[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s;
        """,
        (schema, table_name),
    )
    return {r.get("column_name") for r in (cur.fetchall() or []) if r.get("column_name")}


def _resolve_domain_label(cur, schema: str, table_name: str, pk_value) -> str | None:
    if pk_value is None:
        return None
    table = _validated_identifier(table_name)
    if not _table_exists(cur, schema, table):
        return None

    cols = _table_columns(cur, schema, table)
    if not cols:
        return None

    preferred = [
        "dispname",
        "iliCode",
        "ilicode",
        "nombre",
        "name",
        "descripcion",
        "description",
        "label",
        "tipo_calificar",
    ]
    selected = [c for c in preferred if c in cols]
    if not selected:
        return None

    select_sql = ", ".join(f"t.{_quote_ident(c)} AS {_quote_ident(c)}" for c in selected)
    sql = (
        f"SELECT {select_sql} "
        f"FROM {_quote_ident(schema)}.{_quote_ident(table)} t "
        "WHERE t.t_id::text = %s::text "
        "LIMIT 1;"
    )
    cur.execute(sql, (str(pk_value),))
    row = cur.fetchone() or {}

    for c in selected:
        v = row.get(c)
        if v is None:
            continue
        s = str(v).strip()
        if not s:
            continue
        if s == str(pk_value).strip():
            continue
        return s
    return None


def _normalize_derechos_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for row in rows:
        primer_nombre = row.get("i_primer_nombre") or row.get("primer_nombre")
        segundo_nombre = row.get("i_segundo_nombre") or row.get("segundo_nombre")
        primer_apellido = row.get("i_primer_apellido") or row.get("primer_apellido")
        segundo_apellido = row.get("i_segundo_apellido") or row.get("segundo_apellido")
        razon_social = row.get("i_razon_social") or row.get("razon_social")
        documento_identidad = row.get("i_documento_identidad") or row.get("documento_identidad")

        nombre_persona = " ".join(
            str(v).strip()
            for v in (primer_nombre, segundo_nombre, primer_apellido, segundo_apellido)
            if v is not None and str(v).strip()
        )
        row["nombre_completo"] = razon_social or nombre_persona or documento_identidad or ""
        row["documento_identidad"] = documento_identidad
        row["tipo_nombre"] = row.get("d_tipo_nombre") or row.get("tipo_nombre") or row.get("d_tipo")
        row["tipo_documento_nombre"] = (
            row.get("i_tipo_documento_nombre")
            or row.get("tipo_documento_nombre")
            or row.get("i_tipo_documento")
        )
        row["grupo_etnico_nombre"] = (
            row.get("i_grupo_etnico_nombre")
            or row.get("grupo_etnico_nombre")
            or row.get("i_grupo_etnico")
        )
    return rows


@router.get("/predio/buscar")
def predio_buscar(
    numero_predial: str | None = Query(None),
    matricula: str | None = Query(None),
    direccion: str | None = Query(None),
    documento: str | None = Query(None),
    nombre: str | None = Query(None),
    _user: Annotated[dict[str, Any], Depends(get_current_user)] = None,
    tenant: Annotated[TenantContext, Depends(get_current_tenant)] = None,
    conn=Depends(get_tenant_db_connection),
):
    numero_predial = (numero_predial or "").strip() or None
    matricula = (matricula or "").strip() or None
    direccion = (direccion or "").strip() or None
    documento = (documento or "").strip() or None
    nombre = (nombre or "").strip() or None
    schema = _schema_name(tenant)

    if not any((numero_predial, matricula, direccion, documento, nombre)):
        return JSONResponse(
            {
                "error": (
                    "Envia numero_predial o matricula o direccion o "
                    "documento o nombre"
                )
            },
            status_code=400,
        )

    where: list[str] = []
    params: list[object] = []
    join_ext = False

    if numero_predial:
        where.append("(BTRIM(p.numero_predial::text) = BTRIM(%s::text))")
        params.append(numero_predial)

    if matricula:
        where.append("(p.matricula_inmobiliaria::text = %s)")
        params.append(matricula)

    if direccion:
        join_ext = True
        where.append("(to_jsonb(dx)::text ILIKE %s)")
        params.append(f"%{direccion}%")

    if documento:
        documento_norm = re.sub(r"[^0-9a-zA-Z]+", "", documento).lower()
        if documento_norm:
            where.append(
                """
                EXISTS (
                  SELECT 1
                  FROM {schema}.arb_derechointeresadofuente di
                  WHERE di.predio::text = p.t_id::text
                    AND regexp_replace(
                          lower(coalesce(di.i_documento_identidad::text, '')),
                          '[^0-9a-z]+',
                          '',
                          'g'
                        ) LIKE %s
                )
                """.strip().format(schema=schema)
            )
            params.append(f"%{documento_norm}%")
        else:
            where.append(
                """
                EXISTS (
                  SELECT 1
                  FROM {schema}.arb_derechointeresadofuente di
                  WHERE di.predio::text = p.t_id::text
                    AND di.i_documento_identidad::text ILIKE %s
                )
                """.strip().format(schema=schema)
            )
            params.append(f"%{documento}%")

    if nombre:
        palabras = [p.strip() for p in nombre.split() if p.strip()]
        if not palabras:
            palabras = [nombre.strip()]

        sub_clauses: list[str] = []
        for palabra in palabras:
            sub_clauses.append(
                """
                EXISTS (
                  SELECT 1
                  FROM {schema}.arb_derechointeresadofuente di
                  WHERE di.predio::text = p.t_id::text
                    AND to_jsonb(di)::text ILIKE %s
                )
                """.strip().format(schema=schema)
            )
            params.append(f"%{palabra}%")

        where.append(f"({' AND '.join(sub_clauses)})")

    join_ext_sql = ""
    if join_ext:
        join_ext_sql = f"""
    LEFT JOIN {_qualified_table(tenant, 'arb_direccion')} dx ON dx.arb_predio_direccion = p.t_id
    """

    sql = f"""
    SELECT
      DISTINCT ON (COALESCE(NULLIF(BTRIM(p.numero_predial::text), ''), p.t_id::text))
      p.*,
      p.numero_predial AS numero_predial_nacional,
      uat.dispname AS tipo_nombre,
      c.dispname AS condicion_predio_nombre,
      de.dispname AS destinacion_economica_nombre
    FROM {_qualified_table(tenant, 'arb_predio')} p
    LEFT JOIN {_qualified_table(tenant, 'arb_prediotipo')} uat
      ON uat.t_id::text = p.tipo::text
    LEFT JOIN {_qualified_table(tenant, 'arb_condicionprediotipo')} c
      ON c.t_id::text = p.condicion_predio::text
    LEFT JOIN {_qualified_table(tenant, 'arb_destinacioneconomicatipo')} de
      ON de.t_id::text = p.destinacion_economica::text
    {join_ext_sql}
    WHERE {" OR ".join(where)}
    ORDER BY COALESCE(NULLIF(BTRIM(p.numero_predial::text), ''), p.t_id::text), p.t_id DESC
    LIMIT 20;
    """

    try:
        rows = _execute_fetchall(conn, sql, tuple(params))
    except Exception as exc:
        logger.exception(
            "Error en /predio/buscar municipality=%s schema=%s",
            tenant.municipality_code,
            schema,
        )
        return JSONResponse(
            {"error": f"Error consultando predios: {exc}"},
            status_code=500,
        )

    features = [
        {
            "type": "Feature",
            "geometry": None,
            "properties": r,
        }
        for r in rows
    ]
    return {"type": "FeatureCollection", "features": features}


@router.get("/predio/detalle")
def predio_detalle(
    predio_id: int = Query(..., gt=0),
    _user: Annotated[dict[str, Any], Depends(get_current_user)] = None,
    tenant: Annotated[TenantContext, Depends(get_current_tenant)] = None,
    conn=Depends(get_tenant_db_connection),
):
    schema = _schema_name(tenant)
    sql_base = f"""
    SELECT
      p.*,
      p.numero_predial AS numero_predial_nacional,
      tp.dispname AS tipo_nombre,
      cp.dispname AS condicion_predio_nombre,
      de.dispname AS destinacion_economica_nombre,
      rv.dispname AS resultado_visita_nombre,
      tdoc.dispname AS tipo_documento_quien_atendio_nombre,
      tcapt.dispname AS tipo_captura_nombre,
      efmi.dispname AS estado_fmi_nombre,
      terr.terreno_id,
      terr.terreno_geom
    FROM {_qualified_table(tenant, 'arb_predio')} p
    LEFT JOIN {_qualified_table(tenant, 'arb_prediotipo')} tp
      ON tp.t_id::text = p.tipo::text
    LEFT JOIN {_qualified_table(tenant, 'arb_condicionprediotipo')} cp
      ON cp.t_id::text = p.condicion_predio::text
    LEFT JOIN {_qualified_table(tenant, 'arb_destinacioneconomicatipo')} de
      ON de.t_id::text = p.destinacion_economica::text
    LEFT JOIN {_qualified_table(tenant, 'arb_resultadovisitatipo')} rv
      ON rv.t_id::text = p.resultado_visita::text
    LEFT JOIN {_qualified_table(tenant, 'arb_interesadodocumentotipo')} tdoc
      ON tdoc.t_id::text = p.tipo_documento_quien_atendio::text
    LEFT JOIN {_qualified_table(tenant, 'arb_metodoproducciontipo')} tcapt
      ON tcapt.t_id::text = p.tipo_captura::text
    LEFT JOIN {_qualified_table(tenant, 'arb_estadofmitipo')} efmi
      ON efmi.t_id::text = p.estado_fmi::text
    LEFT JOIN LATERAL (
      SELECT
        t.t_id AS terreno_id,
        ST_AsGeoJSON(t.geometria)::json AS terreno_geom
      FROM {_qualified_table(tenant, 'arb_terreno')} t
      WHERE t.predio::text = p.t_id::text
      ORDER BY t.t_id
      LIMIT 1
    ) terr
      ON TRUE
    WHERE p.t_id = %s
    LIMIT 1;
    """

    sql_uc = f"""
    SELECT
      uc.*,
      car.identificador AS caracteristica_identificador,
      car.total_plantas,
      car.observaciones,
      calif.dispname AS tipo_calificacion_clase,
      COALESCE(calif.dispname, 'Unidad de Construccion ARB') AS tipo_calificacion_resumen,
      ect.dispname AS estado_construccion,
      ST_AsGeoJSON(uc.geometria)::json AS geom
    FROM {_qualified_table(tenant, 'arb_unidadconstruccion')} uc
    JOIN {_qualified_table(tenant, 'arb_construccion')} c
      ON c.t_id = uc.construccion
    LEFT JOIN {_qualified_table(tenant, 'arb_caracteristicasunidadconstruccion')} car
      ON car.t_id = uc.caracteristicasunidadconstruccion
    LEFT JOIN {_qualified_table(tenant, 'arb_calificaciontipo')} calif
      ON calif.t_id::text = car.tipo_calificacion::text
    LEFT JOIN {_qualified_table(tenant, 'arb_estadoconstrucciontipo')} ect
      ON ect.t_id::text = uc.estado_unidad_construccion::text
    WHERE c.predio::text = %s::text;
    """

    sql_dif = f"""
    SELECT
      di.*,
      dt.dispname AS d_tipo_nombre,
      fat.dispname AS fa_tipo_nombre,
      it.dispname AS i_tipo_nombre,
      idt.dispname AS i_tipo_documento_nombre,
      get.dispname AS i_grupo_etnico_nombre,
      njt.dispname AS naturaleza_juridica_nombre,
      cnjt.dispname AS codigo_naturaleza_juridica_nombre,
      st.dispname AS sexo_nombre
    FROM {_qualified_table(tenant, 'arb_derechointeresadofuente')} di
    LEFT JOIN {_qualified_table(tenant, 'arb_derechotipo')} dt
      ON dt.t_id::text = di.d_tipo::text
    LEFT JOIN {_qualified_table(tenant, 'arb_fuenteadministrativatipo')} fat
      ON fat.t_id::text = di.fa_tipo::text
    LEFT JOIN {_qualified_table(tenant, 'arb_interesadotipo')} it
      ON it.t_id::text = di.i_tipo::text
    LEFT JOIN {_qualified_table(tenant, 'arb_interesadodocumentotipo')} idt
      ON idt.t_id::text = di.i_tipo_documento::text
    LEFT JOIN {_qualified_table(tenant, 'arb_grupoetnicotipo')} get
      ON get.t_id::text = di.i_grupo_etnico::text
    LEFT JOIN {_qualified_table(tenant, 'arb_naturalezajuridicatipo')} njt
      ON njt.t_id::text = di.naturaleza_juridica::text
    LEFT JOIN {_qualified_table(tenant, 'arb_codigonaturalezajuridicatipo')} cnjt
      ON cnjt.t_id::text = di.codigo_naturaleza_juridica::text
    LEFT JOIN {_qualified_table(tenant, 'arb_sexotipo')} st
      ON st.t_id::text = di.i_sexo::text
    WHERE di.predio::text = %s::text;
    """

    sql_uebaunit = f"""
    SELECT u.*
    FROM {_qualified_table(tenant, 'arb_uebaunit')} u
    WHERE u.baunit::text = %s::text;
    """

    sql_direcciones = f"""
    SELECT
      dx.*,
      ST_AsGeoJSON(dx.geometria)::json AS geom
    FROM {_qualified_table(tenant, 'arb_direccion')} dx
    WHERE dx.arb_predio_direccion::text = %s::text;
    """

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql_base, (predio_id,))
            base = cur.fetchone()
            if not base:
                return JSONResponse({"error": "Predio no encontrado"}, status_code=404)

            cur.execute(sql_uc, (predio_id,))
            unidades = cur.fetchall()

            if _table_exists(cur, schema, "arb_uebaunit"):
                cur.execute(sql_uebaunit, (predio_id,))
                uebaunit_rows = cur.fetchall()
            else:
                uebaunit_rows = []

            derechos_interesados = []
            direcciones = []

            try:
                cur.execute(sql_dif, (predio_id,))
                derechos_interesados = _normalize_derechos_rows(cur.fetchall())
            except Exception:
                _rollback_safely(conn)
                derechos_interesados = []

            try:
                cur.execute(sql_direcciones, (predio_id,))
                direcciones = cur.fetchall()
            except Exception:
                _rollback_safely(conn)
                direcciones = direcciones or []
    except Exception as exc:
        _rollback_safely(conn)
        logger.exception(
            "Error en /predio/detalle predio_id=%s municipality=%s schema=%s",
            predio_id,
            tenant.municipality_code,
            schema,
        )
        return JSONResponse(
            {
                "error": "Error consultando detalle de predio",
                "predio_id": predio_id,
                "detalle": str(exc),
            },
            status_code=500,
        )

    return {
        "predio": base,
        "unidades_construccion": unidades,
        "derechos": derechos_interesados,
        "interesados": derechos_interesados,
        "uebaunit": uebaunit_rows,
        "novedad_fmi": [],
        "datos_adicionales": [],
        "estructura_novedad_np": [],
        "fuente_administrativa": derechos_interesados,
        "contacto_visita": [],
        "direcciones": direcciones,
        "rrr_interesado": [],
    }


@router.get("/predio/unidad_detalle")
def unidad_detalle(
    unidad_id: int = Query(..., description="ID de arb_unidadconstruccion.t_id"),
    _user: Annotated[dict[str, Any], Depends(get_current_user)] = None,
    tenant: Annotated[TenantContext, Depends(get_current_tenant)] = None,
    conn=Depends(get_tenant_db_connection),
):
    schema = _schema_name(tenant)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if not _table_exists(cur, schema, "arb_unidadconstruccion"):
                return JSONResponse(
                    {"error": "Tabla arb_unidadconstruccion no disponible en el esquema"},
                    status_code=500,
                )

            uc_cols = _table_columns(cur, schema, "arb_unidadconstruccion")
            has_car = _table_exists(cur, schema, "arb_caracteristicasunidadconstruccion")
            car_cols = (
                _table_columns(cur, schema, "arb_caracteristicasunidadconstruccion")
                if has_car
                else set()
            )

            select_parts: list[str] = ["uc.*"]
            join_parts: list[str] = []

            def add_uc_domain(
                col_name: str, domain_table: str, domain_alias: str, output_alias: str
            ) -> None:
                if col_name not in uc_cols:
                    return
                table = _validated_identifier(domain_table)
                if not _table_exists(cur, schema, table):
                    return
                join_parts.append(
                    f"LEFT JOIN {schema}.{table} {domain_alias} "
                    f"ON {domain_alias}.t_id::text = uc.{col_name}::text"
                )
                select_parts.append(
                    "COALESCE("
                    f"{domain_alias}.dispname, "
                    f"to_jsonb({domain_alias})->>'iliCode', "
                    f"to_jsonb({domain_alias})->>'ilicode', "
                    f"{domain_alias}.t_id::text"
                    f") AS {output_alias}"
                )

            add_uc_domain("tipo_planta", "arb_construccionplantatipo", "dtp", "tipo_planta_nombre")
            add_uc_domain(
                "relacion_superficie",
                "arb_relacionsuperficieconstrucciontipo",
                "drs",
                "relacion_superficie_nombre",
            )
            add_uc_domain(
                "estado_unidad_construccion",
                "arb_estadoconstrucciontipo",
                "dec",
                "estado_unidad_construccion_nombre",
            )

            has_uc_car_fk = has_car and "caracteristicasunidadconstruccion" in uc_cols
            if has_uc_car_fk:
                join_parts.append(
                    f"LEFT JOIN {schema}.arb_caracteristicasunidadconstruccion car "
                    "ON car.t_id = uc.caracteristicasunidadconstruccion"
                )
                for col in (
                    "t_id",
                    "identificador",
                    "tipo_unidad_construccion",
                    "total_plantas",
                    "uso",
                    "anio_construccion",
                    "area_construida",
                    "area_privada_construida",
                    "observaciones",
                    "usos_tradicionales_culturales",
                    "comienzo_vida_util_version",
                    "tipo_calificacion",
                    "cc_armazon",
                    "cc_muros",
                    "cc_cubierta",
                    "cc_conservacion_estructura",
                    "cc_fachada",
                    "cc_cubrimiento_muros",
                    "cc_piso",
                    "cc_conservacion_acabados",
                    "cc_tamanio_banio",
                    "cc_enchape_banio",
                    "cc_mobiliario_banio",
                    "cc_conservacion_banio",
                    "cc_tamanio_cocina",
                    "cc_enchape_cocina",
                    "cc_mobiliario_cocina",
                    "cc_conservacion_cocina",
                    "cc_cerchas_complemento_industria",
                    "cc_altura_cerchas_superior_6m",
                    "cc_tipo_calificar",
                    "ct_tipo_tipologia",
                    "ct_conservacion_tipologia",
                    "cnc_tipo_anexo",
                    "cnc_conservacion_anexo",
                ):
                    if col in car_cols:
                        select_parts.append(f"car.{col} AS car_{col}")

                car_domains: list[tuple[str, str, str, str]] = [
                    ("tipo_unidad_construccion", "arb_unidadconstrucciontipo", "d_tuc", "tipo_unidad_construccion_nombre"),
                    ("uso", "arb_usouconstipo", "d_uso", "uso_nombre"),
                    (
                        "usos_tradicionales_culturales",
                        "arb_usostradicionalesculturalestipo",
                        "d_utc",
                        "usos_tradicionales_culturales_nombre",
                    ),
                    ("tipo_calificacion", "arb_calificaciontipo", "d_tcal", "tipo_calificacion_nombre"),
                    ("cc_armazon", "arb_armazontipo", "d_cc_armazon", "armazon_nombre"),
                    ("cc_muros", "arb_murostipo", "d_cc_muros", "muros_nombre"),
                    ("cc_cubierta", "arb_cubiertatipo", "d_cc_cubierta", "cubierta_nombre"),
                    (
                        "cc_conservacion_estructura",
                        "arb_estadoconservaciontipo",
                        "d_cc_cons_estr",
                        "conservacion_estructura_nombre",
                    ),
                    ("cc_fachada", "arb_fachadatipo", "d_cc_fachada", "fachada_nombre"),
                    (
                        "cc_cubrimiento_muros",
                        "arb_cubrimientomurostipo",
                        "d_cc_cubr_muros",
                        "cubrimiento_muros_nombre",
                    ),
                    ("cc_piso", "arb_pisotipo", "d_cc_piso", "piso_nombre"),
                    (
                        "cc_conservacion_acabados",
                        "arb_estadoconservaciontipo",
                        "d_cc_cons_aca",
                        "conservacion_acabados_nombre",
                    ),
                    ("cc_tamanio_banio", "arb_tamaniobaniotipo", "d_cc_tam_ban", "tamanio_banio_nombre"),
                    ("cc_enchape_banio", "arb_enchapebaniotipo", "d_cc_enc_ban", "enchape_banio_nombre"),
                    (
                        "cc_mobiliario_banio",
                        "arb_mobiliariobaniotipo",
                        "d_cc_mob_ban",
                        "mobiliario_banio_nombre",
                    ),
                    (
                        "cc_conservacion_banio",
                        "arb_estadoconservaciontipo",
                        "d_cc_cons_ban",
                        "conservacion_banio_nombre",
                    ),
                    (
                        "cc_tamanio_cocina",
                        "arb_tamaniococinatipo",
                        "d_cc_tam_coc",
                        "tamanio_cocina_nombre",
                    ),
                    (
                        "cc_enchape_cocina",
                        "arb_enchapecocinatipo",
                        "d_cc_enc_coc",
                        "enchape_cocina_nombre",
                    ),
                    (
                        "cc_mobiliario_cocina",
                        "arb_mobiliariococinatipo",
                        "d_cc_mob_coc",
                        "mobiliario_cocina_nombre",
                    ),
                    (
                        "cc_conservacion_cocina",
                        "arb_estadoconservaciontipo",
                        "d_cc_cons_coc",
                        "conservacion_cocina_nombre",
                    ),
                    (
                        "cc_cerchas_complemento_industria",
                        "arb_cerchascomplementoindustriatipo",
                        "d_cc_cer",
                        "cerchas_complemento_industria_nombre",
                    ),
                    ("cc_tipo_calificar", "arb_calificartipo", "d_cc_tipo_cal", "tipo_calificar_nombre"),
                    ("ct_tipo_tipologia", "arb_tipologiatipo", "d_ct_tip", "tipo_tipologia_nombre"),
                    (
                        "ct_conservacion_tipologia",
                        "arb_estadoconservaciontipologiatipo",
                        "d_ct_cons",
                        "conservacion_nombre",
                    ),
                    ("cnc_tipo_anexo", "arb_anexotipo", "d_cnc_tip", "tipo_anexo_nombre"),
                    (
                        "cnc_conservacion_anexo",
                        "arb_estadoconservaciontipologiatipo",
                        "d_cnc_cons",
                        "conservacion_anexo_nombre",
                    ),
                ]

                for fk_col, dom_table, dom_alias, out_alias in car_domains:
                    if fk_col not in car_cols:
                        continue
                    table = _validated_identifier(dom_table)
                    if not _table_exists(cur, schema, table):
                        continue
                    join_parts.append(
                        f"LEFT JOIN {schema}.{table} {dom_alias} "
                        f"ON {dom_alias}.t_id::text = car.{fk_col}::text"
                    )
                    select_parts.append(
                        "COALESCE("
                        f"{dom_alias}.dispname, "
                        f"to_jsonb({dom_alias})->>'iliCode', "
                        f"to_jsonb({dom_alias})->>'ilicode', "
                        f"{dom_alias}.t_id::text"
                        f") AS {out_alias}"
                    )

            sql_unidad = f"""
            SELECT
              {", ".join(select_parts)}
            FROM {schema}.arb_unidadconstruccion uc
            {" ".join(join_parts)}
            WHERE uc.t_id = %s::bigint
            LIMIT 1;
            """

            cur.execute(sql_unidad, (unidad_id,))
            row = cur.fetchone()
            if not row:
                return JSONResponse(
                    {"error": "Unidad de construcción no encontrada"},
                    status_code=404,
                )

            unidad = dict(row)
            car_data: dict[str, object] = {}
            for k, v in row.items():
                if k.startswith("car_"):
                    car_data[k[4:]] = v
            for k in (
                "tipo_unidad_construccion_nombre",
                "uso_nombre",
                "usos_tradicionales_culturales_nombre",
                "tipo_calificacion_nombre",
                "armazon_nombre",
                "muros_nombre",
                "cubierta_nombre",
                "conservacion_estructura_nombre",
                "fachada_nombre",
                "cubrimiento_muros_nombre",
                "piso_nombre",
                "conservacion_acabados_nombre",
                "tamanio_banio_nombre",
                "enchape_banio_nombre",
                "mobiliario_banio_nombre",
                "conservacion_banio_nombre",
                "tamanio_cocina_nombre",
                "enchape_cocina_nombre",
                "mobiliario_cocina_nombre",
                "conservacion_cocina_nombre",
                "cerchas_complemento_industria_nombre",
                "tipo_calificar_nombre",
                "tipo_tipologia_nombre",
                "conservacion_nombre",
                "tipo_anexo_nombre",
                "conservacion_anexo_nombre",
            ):
                if k in row:
                    car_data[k] = row.get(k)

            has_car_values = any(v is not None and str(v).strip() != "" for v in car_data.values())
            caracteristicas = car_data if has_car_values else None

            cc_tipo_calificar_fk = car_data.get("cc_tipo_calificar")
            cc_tipo_calificar_lbl = car_data.get("tipo_calificar_nombre")
            if cc_tipo_calificar_fk is not None and (
                cc_tipo_calificar_lbl is None
                or not str(cc_tipo_calificar_lbl).strip()
                or str(cc_tipo_calificar_lbl).strip() == str(cc_tipo_calificar_fk).strip()
            ):
                resolved = _resolve_domain_label(cur, schema, "arb_calificartipo", cc_tipo_calificar_fk)
                if resolved:
                    car_data["tipo_calificar_nombre"] = resolved
                else:
                    car_data["tipo_calificar_nombre"] = None

            tipo_calif = (car_data.get("tipo_calificacion_nombre") or "").strip().lower()
            tipo_modal = None
            if "no convencional" in tipo_calif:
                tipo_modal = "no_convencional"
            elif "tipolog" in tipo_calif:
                tipo_modal = "tipologia"
            elif "convencional" in tipo_calif:
                tipo_modal = "convencional"

            unidad["tipo_calificacion_modal"] = tipo_modal
            if car_data.get("tipo_calificacion_nombre"):
                unidad["tipo_calificacion_clase"] = car_data.get("tipo_calificacion_nombre")

            calificacion_convencional = None
            if caracteristicas:
                calificacion_convencional = {
                    "tipo_calificacion_nombre": car_data.get("tipo_calificacion_nombre"),
                    "tipo_calificar_nombre": car_data.get("tipo_calificar_nombre"),
                    "armazon_nombre": car_data.get("armazon_nombre"),
                    "muros_nombre": car_data.get("muros_nombre"),
                    "cubierta_nombre": car_data.get("cubierta_nombre"),
                    "conservacion_estructura_nombre": car_data.get("conservacion_estructura_nombre"),
                    "fachada_nombre": car_data.get("fachada_nombre"),
                    "cubrimiento_muros_nombre": car_data.get("cubrimiento_muros_nombre"),
                    "piso_nombre": car_data.get("piso_nombre"),
                    "conservacion_acabados_nombre": car_data.get("conservacion_acabados_nombre"),
                    "tamanio_banio_nombre": car_data.get("tamanio_banio_nombre"),
                    "enchape_banio_nombre": car_data.get("enchape_banio_nombre"),
                    "mobiliario_banio_nombre": car_data.get("mobiliario_banio_nombre"),
                    "conservacion_banio_nombre": car_data.get("conservacion_banio_nombre"),
                    "tamanio_cocina_nombre": car_data.get("tamanio_cocina_nombre"),
                    "enchape_cocina_nombre": car_data.get("enchape_cocina_nombre"),
                    "mobiliario_cocina_nombre": car_data.get("mobiliario_cocina_nombre"),
                    "conservacion_cocina_nombre": car_data.get("conservacion_cocina_nombre"),
                    "cerchas_complemento_industria_nombre": car_data.get("cerchas_complemento_industria_nombre"),
                    "altura_cerchas_superior_6m": car_data.get("cc_altura_cerchas_superior_6m"),
                }
                if "total_calificacion" in car_data:
                    calificacion_convencional["total_calificacion"] = car_data.get("total_calificacion")

            tipologia_construccion = (
                {
                    "tipo_tipologia_nombre": car_data.get("tipo_tipologia_nombre"),
                    "conservacion_nombre": car_data.get("conservacion_nombre"),
                }
                if caracteristicas
                else None
            )

            tipologia_no_convencional = (
                {
                    "tipo_anexo_nombre": car_data.get("tipo_anexo_nombre"),
                    "conservacion_anexo_nombre": car_data.get("conservacion_anexo_nombre"),
                }
                if caracteristicas
                else None
            )
    except Exception as exc:
        _rollback_safely(conn)
        logger.exception(
            "Error en /predio/unidad_detalle unidad_id=%s municipality=%s schema=%s",
            unidad_id,
            tenant.municipality_code,
            schema,
        )
        return JSONResponse(
            {"error": "Error consultando unidad de construccion", "unidad_id": unidad_id, "detalle": str(exc)},
            status_code=500,
        )

    return {
        "unidad": unidad,
        "unidades": [unidad],
        "caracteristicas": caracteristicas,
        "calificacion_convencional": calificacion_convencional,
        "tipologia_construccion": tipologia_construccion,
        "tipologia_no_convencional": tipologia_no_convencional,
    }
