import logging
from typing import List, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from routers.auth import (
    get_current_tenant,
    get_current_user,
    get_user_role,
    normalize_role,
)
from tenants import TenantContext, get_tenant_db_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/predios-generador", tags=["predios-generador"])

# =========================================================
# MODELOS DE ENTRADA Y SALIDA
# =========================================================
class GenerarNpnRequest(BaseModel):
    predio_matriz: str = Field(..., description="NPN de 30 dígitos o identificador del predio matriz de referencia")
    cantidad: int = Field(1, ge=1, le=500, description="Cantidad de nuevos números prediales a generar")
    tipo_mutacion: str = Field("DESENGLOBE", description="Tipo de trámite: DESENGLOBE, PH, MEJORA, SEGREGACION")
    condicion_propiedad: Optional[str] = Field(None, description="Condición de propiedad (00=NPH, 01-89=PH, 88=Mejora, 99=Bien común)")
    edificio: Optional[str] = Field(None, description="Edificio o Torre (2 dígitos, por defecto '00')")
    piso: Optional[str] = Field(None, description="Piso (2 dígitos, por defecto '00')")
    consecutivo_tramite: Optional[str] = Field(None, description="Identificador o radicado del trámite")
    observaciones: Optional[str] = Field(None, description="Notas u observaciones adicionales")

class ItemPredioGenerado(BaseModel):
    id_inventario: int
    codigo_homologado: str
    numero_predial: str
    departamento: str
    municipio: str
    sector: str
    comuna: str
    barrio: str
    manzana: str
    terreno: str
    condicion: str
    edificio: str
    piso: str
    unidad: str
    estado: str
    fecha_reserva: str

class GenerarNpnResponse(BaseModel):
    success: bool
    cantidad_generada: int
    predio_matriz_base: str
    consecutivo_tramite: Optional[str]
    items: List[ItemPredioGenerado]

class LiberarHomologadosRequest(BaseModel):
    codigos: List[str] = Field(..., description="Lista de códigos homologados a liberar/desmarcar de la reserva")

# =========================================================
# VALIDACIÓN DE ACCESO POR ROL
# =========================================================
def _verificar_rol_autorizado(user: dict = Depends(get_current_user)) -> dict:
    role = normalize_role(get_user_role(user or {}))
    # Permitir a coordinador, coordinacion_tecnica, soporte y admin
    if role not in {"coordinador", "coordinacion_tecnica", "soporte", "admin", "administrador"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Acceso denegado: El rol '{role}' no tiene permisos para generar números prediales ni reservar códigos homologados."
        )
    return user

# =========================================================
# REGLAS CATASTRALES DE 30 DÍGITOS (Resolución IGAC / Neiva)
# Pos 1-13:  Prefijo Territorial (Depto 2, Mpio 3, Sector 2, Comuna 2, Barrio 4) -> 13 dígitos
# Pos 14-17: Manzana (4 dígitos)
# Pos 18-21: Terreno / Predio en la Manzana (4 dígitos)
# Pos 22:    Condición del Predio (1 dígito: 0, 9, 8, 7, 5, 4, 3, 2)
# Pos 23-24: Edificio / Torre (2 dígitos: 00 a 99)
# Pos 25-26: Piso (2 dígitos: 00 a 99)
# Pos 27-30: Unidad Predial en PH/Condominio (4 dígitos: 0001 a 9999) o '0000' en NPH
# Total: 13 + 4 + 4 + 1 + 2 + 2 + 4 = 30 dígitos
# =========================================================
def _desglosar_npn(npn: str) -> dict:
    npn_limpio = "".join([c for c in str(npn).strip() if c.isdigit()])
    if len(npn_limpio) != 30:
        raise HTTPException(
            status_code=400,
            detail=f"El número predial matriz '{npn}' debe tener exactamente 30 dígitos numéricos (actualmente tiene {len(npn_limpio)})."
        )
    return {
        "prefijo_13": npn_limpio[0:13],      # Pos 1-13
        "manzana": npn_limpio[13:17],        # Pos 14-17 (4 dígitos)
        "terreno": npn_limpio[17:21],        # Pos 18-21 (4 dígitos)
        "condicion": npn_limpio[21:22],      # Pos 22 (1 dígito)
        "edificio": npn_limpio[22:24],       # Pos 23-24 (2 dígitos)
        "piso": npn_limpio[24:26],           # Pos 25-26 (2 dígitos)
        "unidad": npn_limpio[26:30],         # Pos 27-30 (4 dígitos)
    }

def _construir_npn(d: dict) -> str:
    prefijo_13 = str(d["prefijo_13"]).zfill(13)[:13]
    manzana = str(d["manzana"]).zfill(4)[:4]
    terreno = str(d["terreno"]).zfill(4)[:4]
    condicion = str(d["condicion"]).strip()[:1] or "0"
    edificio = str(d["edificio"]).zfill(2)[:2]
    piso = str(d["piso"]).zfill(2)[:2]
    unidad = str(d["unidad"]).zfill(4)[:4]
    return f"{prefijo_13}{manzana}{terreno}{condicion}{edificio}{piso}{unidad}"

# =========================================================
# ENDPOINTS
# =========================================================

@router.get("/inventario-resumen")
def resumen_inventario(
    user: dict = Depends(_verificar_rol_autorizado),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    """Retorna el estado en tiempo real del inventario de códigos homologados."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT 
                COUNT(*) FILTER (WHERE estado = 'DISPONIBLE') AS disponibles,
                COUNT(*) FILTER (WHERE estado = 'RESERVADO') AS reservados,
                COUNT(*) FILTER (WHERE estado = 'ASIGNADO') AS asignados,
                COUNT(*) AS total
            FROM arbimaps_app.codigos_homologados;
        """)
        row = cur.fetchone() or {"disponibles": 0, "reservados": 0, "asignados": 0, "total": 0}
        return {
            "success": True,
            "resumen": {
                "disponibles": row["disponibles"],
                "reservados": row["reservados"],
                "asignados": row["asignados"],
                "total": row["total"],
            }
        }


@router.get("/sugerir-consecutivos-territoriales")
def sugerir_consecutivos_territoriales(
    sector: str = Query("01", description="Sector territorial (01=Urbano, 00=Rural)"),
    comuna: str = Query("01", description="Comuna o Corregimiento (2 dígitos)"),
    barrio: str = Query("0000", description="Barrio o Vereda (4 dígitos)"),
    user: dict = Depends(_verificar_rol_autorizado),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    """
    Rastrea en tiempo real y alta velocidad el último consecutivo existente de Manzana, Barrio y Comuna
    en la base de datos para sugerir el siguiente número correlativo sin dejar vacíos.
    """
    depto = "41"
    mpio = "001"
    sec = sector.strip().zfill(2)[:2]
    com = comuna.strip().zfill(2)[:2]
    bar = barrio.strip().zfill(4)[:4]
    
    prefijo_13 = f"{depto}{mpio}{sec}{com}{bar}"
    prefijo_9 = f"{depto}{mpio}{sec}{com}"
    prefijo_7 = f"{depto}{mpio}{sec}"
    schema_main = tenant.schemas.main or "a_base_principal"
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # 1. Manzanas en base principal
        cur.execute(f"""
            SELECT MAX(SUBSTRING(numero_predial, 14, 4)::int) AS max_manzana,
                   COUNT(DISTINCT SUBSTRING(numero_predial, 14, 4)) AS total_manzanas
            FROM {schema_main}.arb_predio
            WHERE numero_predial LIKE %s
              AND length(numero_predial) = 30
              AND SUBSTRING(numero_predial, 14, 4) ~ '^[0-9]+$';
        """, (f"{prefijo_13}%",))
        res_m1 = cur.fetchone() or {}
        max_m1 = res_m1.get("max_manzana") or 0
        total_m = res_m1.get("total_manzanas") or 0
        
        # Manzanas en homologados
        cur.execute("""
            SELECT MAX(SUBSTRING(numero_predial, 14, 4)::int) AS max_manzana
            FROM arbimaps_app.codigos_homologados
            WHERE numero_predial LIKE %s
              AND length(numero_predial) = 30
              AND SUBSTRING(numero_predial, 14, 4) ~ '^[0-9]+$';
        """, (f"{prefijo_13}%",))
        res_m2 = cur.fetchone() or {}
        max_m2 = res_m2.get("max_manzana") or 0
        
        max_m = max(max_m1, max_m2)
        sig_m = str(max_m + 1).zfill(4)
        
        # 2. Barrios/Veredas
        cur.execute(f"""
            SELECT MAX(SUBSTRING(numero_predial, 10, 4)::int) AS max_barrio
            FROM {schema_main}.arb_predio
            WHERE numero_predial LIKE %s
              AND length(numero_predial) = 30
              AND SUBSTRING(numero_predial, 10, 4) ~ '^[0-9]+$';
        """, (f"{prefijo_9}%",))
        res_b = cur.fetchone() or {}
        max_b = res_b.get("max_barrio") or 0
        sig_b = str(max_b + 1).zfill(4)

        # 3. Comunas
        cur.execute(f"""
            SELECT MAX(SUBSTRING(numero_predial, 8, 2)::int) AS max_comuna
            FROM {schema_main}.arb_predio
            WHERE numero_predial LIKE %s
              AND length(numero_predial) = 30
              AND SUBSTRING(numero_predial, 8, 2) ~ '^[0-9]+$';
        """, (f"{prefijo_7}%",))
        res_c = cur.fetchone() or {}
        max_c = res_c.get("max_comuna") or 0
        sig_c = str(max_c + 1).zfill(2)
        
        npn_base_sugerido = f"{prefijo_13}{sig_m}0000000000000"
        
        return {
            "success": True,
            "sector": sec,
            "comuna": com,
            "barrio": bar,
            "prefijo_13": prefijo_13,
            "max_manzana_existente": str(max_m).zfill(4),
            "siguiente_manzana_sugerida": sig_m,
            "total_manzanas_en_zona": total_m,
            "max_barrio_existente": str(max_b).zfill(4),
            "siguiente_barrio_sugerido": sig_b,
            "max_comuna_existente": str(max_c).zfill(2),
            "siguiente_comuna_sugerida": sig_c,
            "npn_base_sugerido": npn_base_sugerido,
        }


@router.get("/catalogo-territorial")
def obtener_catalogo_territorial(
    user: dict = Depends(_verificar_rol_autorizado),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    """
    Retorna el catálogo oficial de Sectores, Comunas urbanas, Corregimientos
    y las 80 Veredas oficiales de Neiva registradas en cartografía catastral.
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Veredas oficiales
        veredas = []
        try:
            cur.execute("""
                SELECT codigo, nombre 
                FROM c_cartografia_catastral.cc_vereda 
                ORDER BY codigo ASC;
            """)
            for r in cur.fetchall():
                cod_str = str(r["codigo"] or "")
                # Extraer los 4 dígitos de la vereda (pos 14 a 17 del código largo o últimos 4)
                cod_4d = cod_str[-4:] if len(cod_str) >= 4 else cod_str.zfill(4)
                veredas.append({
                    "codigo_completo": cod_str,
                    "codigo_4d": cod_4d,
                    "nombre": r["nombre"]
                })
        except Exception as exc:
            logger.warning("Excepcion en predios_generador_api: %s", exc)

        # Si no hay en c_cartografia_catastral, consultar las veredas con predios existentes
        if not veredas:
            cur.execute("""
                SELECT DISTINCT SUBSTRING(numero_predial, 10, 4) AS cod_4d
                FROM a_base_principal.arb_predio
                WHERE length(numero_predial) = 30 AND SUBSTRING(numero_predial, 10, 4) <> '0000'
                ORDER BY cod_4d;
            """)
            for r in cur.fetchall():
                veredas.append({
                    "codigo_4d": r["cod_4d"],
                    "nombre": f"Vereda {r['cod_4d']}"
                })

        return {
            "success": True,
            "sectores": [
                {"codigo": "01", "nombre": "01 - Urbano (Comunas 01 a 10)"},
                {"codigo": "00", "nombre": "00 - Rural General"},
                {"codigo": "02", "nombre": "02 - Corregimiento Río Las Ceibas"},
                {"codigo": "03", "nombre": "03 - Corregimiento Vegalarga"},
                {"codigo": "04", "nombre": "04 - Corregimiento Fortalecillas"},
                {"codigo": "05", "nombre": "05 - Corregimiento El Caguán"},
                {"codigo": "06", "nombre": "06 - Corregimiento Guacirco"},
                {"codigo": "07", "nombre": "07 - Corregimiento San Antonio"},
                {"codigo": "08", "nombre": "08 - Corregimiento Chapinero / Aipecito"}
            ],
            "comunas_urbanas": [
                {"codigo": str(i).zfill(2), "nombre": f"Comuna {str(i).zfill(2)}"} for i in range(1, 11)
            ],
            "total_veredas": len(veredas),
            "veredas": veredas
        }


@router.post("/generar-npn-homologados", response_model=GenerarNpnResponse)
def generar_npn_y_reservar(
    payload: GenerarNpnRequest,
    user: dict = Depends(_verificar_rol_autorizado),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    """
    Genera N números prediales de 30 dígitos aplicando la norma catastral de Neiva:
    - Conserva el prefijo territorial (pos 1-13) y la manzana (pos 14-17).
    - Para NPH (0, 4, 3, 2): Consecutivo de Terreno (pos 18-21), Edificio=00, Piso=00, Unidad=0000.
    - Para PH/Condominio/Cementerio/Mejoras (9, 8, 7, 5): Fija Terreno (pos 18-21), Edificio (pos 23-24), Piso (pos 25-26) y Consecutivo de Unidad (pos 27-30).
    - Reserva de forma atómica N códigos homologados disponibles.
    """
    username = user.get("username") if isinstance(user, dict) else str(user)
    partes_base = _desglosar_npn(payload.predio_matriz)
    
    # 1. Base territorial de la manzana (17 dígitos: Pos 1-13 + Manzana 14-17)
    prefijo_manzana = f"{partes_base['prefijo_13']}{partes_base['manzana']}"
    
    # 2. Consultar el conjunto de predios existentes para garantizar NO REPETICIÓN cruzada
    schema_main = tenant.schemas.main or "a_base_principal"
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        query_existentes = f"""
            SELECT DISTINCT numero_predial
            FROM (
                SELECT numero_predial FROM {schema_main}.arb_predio 
                WHERE numero_predial LIKE %s AND length(numero_predial) = 30
                UNION
                SELECT numero_predial FROM f_r1_r2.r1_predio_propietario 
                WHERE numero_predial LIKE %s AND length(numero_predial) = 30
                UNION
                SELECT numero_predial FROM arbimaps_app.codigos_homologados 
                WHERE numero_predial LIKE %s AND length(numero_predial) = 30
            ) todos_npn
        """
        like_pattern = f"{prefijo_manzana}%"
        cur.execute(query_existentes, (like_pattern, like_pattern, like_pattern))
        npns_existentes = {r["numero_predial"] for r in cur.fetchall() if r.get("numero_predial")}
        
        # 3. Determinar condición (Posición 22: 1 dígito)
        # 0 = No propiedad horizontal (NPH)
        # 9 = Predios en Propiedad Horizontal (PH)
        # 5 = Mejoras por edificaciones en terreno ajeno de propiedad no reglamentaria en PH
        # 8 = Predio en condominio
        # 7 = Parque cementerios
        # 4 = Vías
        # 3 = Bienes de uso público diferentes a las vías
        # 2 = Informal
        cond_raw = str(payload.condicion_propiedad or "0").strip()
        primer_digito_cond = cond_raw[0] if cond_raw else "0"

        tipo_mut = (payload.tipo_mutacion or "DESENGLOBE").upper().strip()
        es_tramite_unidades = (primer_digito_cond in {"9", "8", "7", "5"}) or (tipo_mut in {"PH", "CONDOMINIO", "MEJORA_PH"})

        nuevos_npns: List[dict] = []
        
        if es_tramite_unidades and tipo_mut != "DESENGLOBE":
            # EN PH / CONDOMINIO / CEMENTERIOS / MEJORAS (9, 8, 7, 5):
            # Pos 18-21: Terreno matriz fijo
            # Pos 22: Condición (9, 8, 7, 5)
            # Pos 23-24: Edificio (2 dígitos, ej. 00 o 01)
            # Pos 25-26: Piso (2 dígitos, ej. 00 o 01)
            # Pos 27-30: Unidad consecutiva (4 dígitos: 0001, 0002...)
            terreno_fijo = partes_base["terreno"]
            edificio_val = (payload.edificio if payload.edificio is not None else partes_base["edificio"]).zfill(2)[:2]
            piso_val = (payload.piso if payload.piso is not None else partes_base["piso"]).zfill(2)[:2]
            
            # Buscar unidades existentes con este prefijo (Manzana + Terreno + Condición + Edificio + Piso)
            prefijo_torre = f"{prefijo_manzana}{terreno_fijo}{primer_digito_cond}{edificio_val}{piso_val}"
            unidades_usadas = set()
            for npn in npns_existentes:
                if npn.startswith(prefijo_torre):
                    try:
                        unidades_usadas.add(int(npn[26:30]))
                    except ValueError:
                        pass
                elif npn.startswith(f"{prefijo_manzana}{terreno_fijo}") and npn[21] == primer_digito_cond:
                    # También rastrear unidades globales dentro del mismo terreno/condición
                    try:
                        unidades_usadas.add(int(npn[26:30]))
                    except ValueError:
                        pass
            
            max_unidad = max(unidades_usadas) if unidades_usadas else 0
            siguiente_unidad = max_unidad + 1 if max_unidad > 0 else 1
            
            while len(nuevos_npns) < payload.cantidad:
                if siguiente_unidad not in unidades_usadas:
                    p = dict(partes_base)
                    p["terreno"] = terreno_fijo
                    p["condicion"] = primer_digito_cond
                    p["edificio"] = edificio_val
                    p["piso"] = piso_val
                    p["unidad"] = str(siguiente_unidad).zfill(4) # Pos 27-30 (4 dígitos)
                    npn_candidato = _construir_npn(p)
                    if npn_candidato not in npns_existentes:
                        nuevos_npns.append(p)
                        npns_existentes.add(npn_candidato)
                siguiente_unidad += 1
        else:
            # EN NPH / DESENGLOBE / SUBDIVISIÓN / VÍAS / BIENES PÚBLICOS / INFORMAL (0, 4, 3, 2):
            # Pos 18-21: Consecutivo de Terreno
            # Pos 22: Condición (0, 4, 3, 2)
            # Pos 23-24: Edificio = '00'
            # Pos 25-26: Piso = '00'
            # Pos 27-30: Unidad = '0000'
            edificio_val = "00"
            piso_val = "00"
            unidad_val = "0000"
            
            terrenos_usados = set()
            for npn in npns_existentes:
                try:
                    terrenos_usados.add(int(npn[17:21]))
                except ValueError:
                    pass
            
            # Buscar el último terreno registrado en esta manzana
            max_terreno = max(terrenos_usados) if terrenos_usados else int(partes_base.get("terreno", "0000"))
            siguiente_terreno = max_terreno + 1 if max_terreno > 0 else 1
            
            while len(nuevos_npns) < payload.cantidad:
                if siguiente_terreno not in terrenos_usados:
                    p = dict(partes_base)
                    p["terreno"] = str(siguiente_terreno).zfill(4) # Pos 18-21 (4 dígitos)
                    p["condicion"] = primer_digito_cond             # Pos 22 (1 dígito)
                    p["edificio"] = edificio_val                    # Pos 23-24 ('00')
                    p["piso"] = piso_val                            # Pos 25-26 ('00')
                    p["unidad"] = unidad_val                        # Pos 27-30 ('0000')
                    npn_candidato = _construir_npn(p)
                    if npn_candidato not in npns_existentes:
                        nuevos_npns.append(p)
                        npns_existentes.add(npn_candidato)
                siguiente_terreno += 1

        # 4. Bloquear y reservar N códigos homologados disponibles (FOR UPDATE SKIP LOCKED)
        cur.execute("""
            SELECT id, codigo_homologado 
            FROM arbimaps_app.codigos_homologados
            WHERE estado = 'DISPONIBLE'
            ORDER BY id ASC
            LIMIT %s
            FOR UPDATE SKIP LOCKED;
        """, (payload.cantidad,))
        
        filas_homologados = cur.fetchall()
        if len(filas_homologados) < payload.cantidad:
            conn.rollback()
            raise HTTPException(
                status_code=400,
                detail=f"Inventario insuficiente: Se solicitaron {payload.cantidad} códigos pero solo hay {len(filas_homologados)} disponibles en la bolsa."
            )
        
        # 5. Actualizar los códigos a estado 'RESERVADO' vinculando el NPN y auditoría
        items_resultado: List[ItemPredioGenerado] = []
        fecha_reserva_str = datetime.now(timezone.utc).isoformat()
        
        for idx, h_row in enumerate(filas_homologados):
            h_id = h_row["id"]
            ch_codigo = h_row["codigo_homologado"]
            npn_obj = nuevos_npns[idx]
            npn_str = _construir_npn(npn_obj)
            
            obs_full = f"Reserva de trámite {payload.consecutivo_tramite or 'S/N'}. {payload.observaciones or ''}".strip()
            
            cur.execute("""
                UPDATE arbimaps_app.codigos_homologados
                SET estado = 'RESERVADO',
                    numero_predial = %s,
                    observaciones = %s,
                    usuario = %s,
                    fecha_asignacion = NOW()
                WHERE id = %s;
            """, (npn_str, obs_full, username, h_id))
            
            items_resultado.append(ItemPredioGenerado(
                id_inventario=h_id,
                codigo_homologado=ch_codigo,
                numero_predial=npn_str,
                departamento=npn_str[0:2],
                municipio=npn_str[2:5],
                sector=npn_str[5:7],
                comuna=npn_str[7:9],
                barrio=npn_str[9:13],
                manzana=npn_str[13:17],
                terreno=npn_str[17:21],
                condicion=npn_str[21:22],
                edificio=npn_str[22:24],
                piso=npn_str[24:26],
                unidad=npn_str[26:30],
                estado="RESERVADO",
                fecha_reserva=fecha_reserva_str,
            ))
            
        conn.commit()
        
        return GenerarNpnResponse(
            success=True,
            cantidad_generada=len(items_resultado),
            predio_matriz_base=payload.predio_matriz,
            consecutivo_tramite=payload.consecutivo_tramite,
            items=items_resultado,
        )


@router.get("/reservas-activas")
def listar_reservas_activas(
    user: dict = Depends(_verificar_rol_autorizado),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    """
    Retorna la lista de todas las reservas activas (estado 'RESERVADO')
    con su NPN propuesto, código homologado, usuario responsable y fecha.
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT 
                id,
                codigo_homologado,
                numero_predial,
                observaciones,
                usuario,
                fecha_asignacion,
                estado
            FROM arbimaps_app.codigos_homologados
            WHERE estado = 'RESERVADO'
            ORDER BY fecha_asignacion DESC NULLS LAST, id DESC;
        """)
        filas = cur.fetchall()
        
        items = []
        for r in filas:
            items.append({
                "id": r["id"],
                "codigo_homologado": r["codigo_homologado"],
                "numero_predial": r["numero_predial"] or "",
                "observaciones": r["observaciones"] or "",
                "usuario": r["usuario"] or "Desconocido",
                "fecha_asignacion": r["fecha_asignacion"].isoformat() if r.get("fecha_asignacion") else "",
                "estado": r["estado"]
            })
            
        return {
            "success": True,
            "total_reservados": len(items),
            "items": items
        }


@router.post("/liberar-homologados")
def liberar_homologados(
    payload: LiberarHomologadosRequest,
    user: dict = Depends(_verificar_rol_autorizado),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    """
    Libera códigos que estaban en estado 'RESERVADO' devolviéndolos a 'DISPONIBLE'
    si el trámite no se consolidó en Alfa.
    """
    if not payload.codigos:
        raise HTTPException(status_code=400, detail="Debe enviar al menos un código a liberar.")
        
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE arbimaps_app.codigos_homologados
            SET estado = 'DISPONIBLE',
                numero_predial = NULL,
                observaciones = NULL,
                usuario = NULL,
                fecha_asignacion = NULL
            WHERE codigo_homologado = ANY(%s)
              AND estado = 'RESERVADO';
        """, (payload.codigos,))
        afectados = cur.rowcount
        conn.commit()
        
        return {
            "success": True,
            "codigos_liberados": afectados,
            "mensaje": f"Se liberaron exitosamente {afectados} códigos homologados hacia la bolsa disponible."
        }


@router.post("/consolidar-homologados")
def consolidar_homologados(
    payload: LiberarHomologadosRequest,
    user: dict = Depends(_verificar_rol_autorizado),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    """
    Consolida códigos que estaban en estado 'RESERVADO' cambiándolos a 'ASIGNADO'
    para dejarlos fijos de manera definitiva en la base de datos tras su creación en Alfa.
    """
    if not payload.codigos:
        raise HTTPException(status_code=400, detail="Debe enviar al menos un código a consolidar.")
        
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE arbimaps_app.codigos_homologados
            SET estado = 'ASIGNADO',
                fecha_asignacion = NOW()
            WHERE codigo_homologado = ANY(%s)
              AND estado = 'RESERVADO';
        """, (payload.codigos,))
        afectados = cur.rowcount
        conn.commit()
        
        return {
            "success": True,
            "codigos_consolidados": afectados,
            "mensaje": f"Se consolidaron exitosamente {afectados} códigos en estado definitivo (ASIGNADO)."
        }
