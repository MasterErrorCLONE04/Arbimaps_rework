"""
Catálogo simplificado de tablas, dominios y relaciones del proyecto ARBIMAPS.

Los datos provienen del proyecto QGIS ``prueba_validadores.qgz`` y permiten que los
validadores conozcan cómo se enlazan las tablas operativas (Predio, Terreno, etc.)
con las tablas de dominios (ARB_*Tipo).  La estructura se puede extender con más
tablas/reglas según se vayan implementando validaciones adicionales.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping


@dataclass(frozen=True)
class Relation:
    """Describe el vínculo entre un campo local y una tabla destino."""

    field: str
    target_table: str
    target_field: str = "t_id"
    relation_id: str | None = None


@dataclass(frozen=True)
class TableSchema:
    """Información resumida de una tabla operativa o de dominios."""

    name: str
    key: str = "t_id"
    fields: Mapping[str, str] = field(default_factory=dict)
    relations: Mapping[str, Relation] = field(default_factory=dict)


def _relation(field: str, target_table: str, relation_id: str | None = None) -> Relation:
    return Relation(field=field, target_table=target_table, relation_id=relation_id)


# Catálogo parcial de dominios ARB_*Tipo (se puede extender según sea necesario)
DOMAIN_TABLES: Dict[str, TableSchema] = {
    "ARB_CondicionPredioTipo": TableSchema(name="ARB_CondicionPredioTipo"),
    "ARB_DestinacionEconomicaTipo": TableSchema(name="ARB_DestinacionEconomicaTipo"),
    "ARB_EstadoFMITipo": TableSchema(name="ARB_EstadoFMITipo"),
    "ARB_ResultadovisitaTipo": TableSchema(name="ARB_ResultadoVisitaTipo"),
    "ARB_MetodoProduccionTipo": TableSchema(name="ARB_MetodoProduccionTipo"),
    "ARB_InteresadoDocumentoTipo": TableSchema(name="ARB_InteresadoDocumentoTipo"),
    "ARB_PredioTipo": TableSchema(name="ARB_PredioTipo"),
    "ARB_TipoReferenciaTipo": TableSchema(name="ARB_PuntoReferenciaTipo"),
    "ARB_EstadoTerrenoTipo": TableSchema(name="ARB_EstadoTerrenoTipo"),
    "ARB_RelacionSuperficieTerrenoTipo": TableSchema(name="ARB_RelacionSuperficieTerrenoTipo"),
    "ARB_EntidadTipo": TableSchema(name="ARB_EntidadTipo"),
    "ARB_TramiteTipo": TableSchema(name="ARB_TramiteTipo"),
    "ARB_TipoConstruccionTipo": TableSchema(name="ARB_TipoConstruccionTipo"),
    "ARB_EstadoConstruccionTipo": TableSchema(name="ARB_EstadoConstruccionTipo"),
    "ARB_RelacionSuperficieConstruccionTipo": TableSchema(name="ARB_RelacionSuperficieConstruccionTipo"),
    "ARB_ConstruccionPlantaTipo": TableSchema(name="ARB_ConstruccionPlantaTipo"),
    "ARB_TipoCalificacionTipo": TableSchema(name="ARB_TipoCalificacionTipo"),
    "ARB_CubiertaTipo": TableSchema(name="ARB_CubiertaTipo"),
    "ARB_EnchapeBanioTipo": TableSchema(name="ARB_EnchapeBanioTipo"),
    "ARB_EnchapeCocinaTipo": TableSchema(name="ARB_EnchapeCocinaTipo"),
    "ARB_MobiliarioBanioTipo": TableSchema(name="ARB_MobiliarioBanioTipo"),
    "ARB_MobiliarioCocinaTipo": TableSchema(name="ARB_MobiliarioCocinaTipo"),
    "ARB_MurosTipo": TableSchema(name="ARB_MurosTipo"),
    "ARB_PisoTipo": TableSchema(name="ARB_PisoTipo"),
    "ARB_TamanoBanioTipo": TableSchema(name="ARB_TamanoBanioTipo"),
    "ARB_TamanoCocinaTipo": TableSchema(name="ARB_TamanoCocinaTipo"),
    "ARB_AnexoTipo": TableSchema(name="ARB_AnexoTipo"),
    "ARB_TipologiaTipo": TableSchema(name="ARB_TipologiaTipo"),
    "ARB_CalificarTipo": TableSchema(name="ARB_CalificarTipo"),
    "ARB_UsoUCNSTipo": TableSchema(name="ARB_UsoUConsTipo"),
    "ARB_UsosTradicionalesCulturalesTipo": TableSchema(name="ARB_UsosTradicionalesCulturalesTipo"),
    "ARB_CodigoNaturalezaJuridicaTipo": TableSchema(name="ARB_CodigoNaturalezaJuridicaTipo"),
    "ARB_NaturalezaJuridicaTipo": TableSchema(name="ARB_NaturalezaJuridicaTipo"),
}


TABLE_SCHEMAS: Dict[str, TableSchema] = {
    "ARB_Predio": TableSchema(
        name="ARB_Predio",
        fields={
            "numero_predial_nacional": "text",
            "condicion_predio": "int",
            "destinacion_eco": "int",
            "estado_fmi": "int",
            "resultado_visita": "int",
            "tipo_captura": "int",
            "tipo_documento_quien_atendio": "int",
            "tipo": "int",
        },
        relations={
            "condicion_predio": _relation("condicion_predio", "ARB_CondicionPredioTipo", "arb_predio_condicion_predio_fkey"),
            "destinacion_economica": _relation("destinacion_economica", "ARB_DestinacionEconomicaTipo", "arb_predio_destinacion_economica_fkey"),
            "estado_fmi": _relation("estado_fmi", "ARB_EstadoFMITipo", "arb_predio_estado_fmi_fkey"),
            "resultado_visita": _relation("resultado_visita", "ARB_ResultadoVisitaTipo", "arb_predio_resultado_visita_fkey"),
            "tipo_captura": _relation("tipo_captura", "ARB_MetodoProduccionTipo", "arb_predio_tipo_captura_fkey"),
            "tipo_documento_quien_atendio": _relation("tipo_documento_quien_atendio", "ARB_InteresadoDocumentoTipo", "arb_predio_tipo_documento_quien_tndio_fkey"),
            "tipo": _relation("tipo", "ARB_PredioTipo", "arb_predio_tipo_fkey"),
        },
    ),
    "ARB_Terreno": TableSchema(
        name="ARB_Terreno",
        relations={
            "estado_terreno": _relation("estado_terreno", "ARB_EstadoTerrenoTipo", "arb_terreno_estado_terreno_fkey"),
            "predio": _relation("predio", "ARB_Predio", "arb_terreno_predio_fkey"),
            "relacion_superficie": _relation("relacion_superficie", "ARB_RelacionSuperficieTerrenoTipo", "arb_terreno_relacion_superficie_fkey"),
        },
    ),
    "ARB_TerrenoHistorico": TableSchema(
        name="ARB_TerrenoHistorico",
        relations={
            "predio": _relation("predio", "ARB_Predio", "arb_terrenohistorico_predio_fkey"),
        },
    ),
    "ARB_Construccion": TableSchema(
        name="ARB_Construccion",
        relations={
            "predio": _relation("predio", "ARB_Predio", "arb_construccion_predio_fkey"),
            "estado_construccion": _relation("estado_construccion", "ARB_EstadoConstruccionTipo", "arb_construccion_estado_construccion_fkey"),
            "tipo_construccion": _relation("tipo_construccion", "ARB_TipoConstruccionTipo", "arb_construccion_tipo_construccion_fkey"),
        },
    ),
    "ARB_UnidadConstruccion": TableSchema(
        name="ARB_UnidadConstruccion",
        relations={
            "construccion": _relation("construccion", "ARB_Construccion", "arb_unidadconstruccion_construccion_fkey"),
            "estado_unidad_construccion": _relation("estado_unidad_construccion", "ARB_EstadoConstruccionTipo", "arb_unidadconstruccion_estado_unidad_construccion_fkey"),
            "relacion_superficie": _relation("relacion_superficie", "ARB_RelacionSuperficieConstruccionTipo", "arb_unidadconstruccion_relacion_superficie_fkey"),
            "tipo_planta": _relation("tipo_planta", "ARB_ConstruccionPlantaTipo", "arb_unidadconstruccion_tipo_planta_fkey"),
        },
    ),
    "ARB_CaracteristicasUnidadConstruccion": TableSchema(
        name="ARB_CaracteristicasUnidadConstruccion",
        relations={
            "cc_armazon": _relation("cc_armazon", "ARB_ArmazonTipo", "arb_crctrstsdnstrccion_cc_armazon_fkey"),
            "cc_cubierta": _relation("cc_cubierta", "ARB_CubiertaTipo", "arb_crctrstsdnstrccion_cc_cubierta_fkey"),
            "cc_conservacion_banio": _relation("cc_conservacion_banio", "ARB_EstadoConservacionTipo", "arb_crctrstsdnstrccion_cc_conservacion_banio_fkey"),
            "cc_conservacion_cocina": _relation("cc_conservacion_cocina", "ARB_EstadoConservacionTipo", "arb_crctrstsdnstrccion_cc_conservacion_cocina_fkey"),
            "cc_conservacion_estructura": _relation("cc_conservacion_estructura", "ARB_EstadoConservacionTipo", "arb_crctrstsdnstrccion_cc_conservacion_estructura_fkey"),
            "cc_mobiliario_banio": _relation("cc_mobiliario_banio", "ARB_MobiliarioBanioTipo", "arb_crctrstsdnstrccion_cc_mobiliario_banio_fkey"),
            "cc_mobiliario_cocina": _relation("cc_mobiliario_cocina", "ARB_MobiliarioCocinaTipo", "arb_crctrstsdnstrccion_cc_mobiliario_cocina_fkey"),
            "cc_piso": _relation("cc_piso", "ARB_PisoTipo", "arb_crctrstsdnstrccion_cc_piso_fkey"),
            "ct_tipo_tipologia": _relation("ct_tipo_tipologia", "ARB_TipologiaTipo", "arb_crctrstsdnstrccion_ct_tipo_tipologia_fkey"),
            "tipo_calificacion": _relation("tipo_calificacion", "ARB_TipoCalificacionTipo", "arb_crctrstsdnstrccion_tipo_calificacion_fkey"),
        },
    ),
    "ARB_DerechoInteresadoFuente": TableSchema(
        name="ARB_DerechoInteresadoFuente",
        relations={
            "d_tipo": _relation("d_tipo", "ARB_DerechoTipo", "arb_derechointeresadofuente_d_tipo_fkey"),
            "fa_tipo": _relation("fa_tipo", "ARB_FuenteAdministrativaTipo", "arb_derechointeresadofuente_fa_tipo_fkey"),
            "i_tipo": _relation("i_tipo", "ARB_InteresadoTipo", "arb_derechointeresadofuente_i_tipo_fkey"),
            "i_tipo_documento": _relation("i_tipo_documento", "ARB_InteresadoDocumentoTipo", "arb_derechointeresadofuente_i_tipo_documento_fkey"),
            "i_grupo_etnico": _relation("i_grupo_etnico", "ARB_GrupoEtnicoTipo", "arb_derechointeresadofuente_i_grupo_etnico_fkey"),
            "naturaliza_juridica": _relation("naturaliza_juridica", "ARB_NaturalezaJuridicaTipo", "arb_derechointeresadofuente_naturaleza_juridica_fkey"),
        },
    ),
    "ARB_PuntoReferencia": TableSchema(
        name="ARB_PuntoReferencia",
        relations={
            "predio": _relation("predio", "ARB_Predio", "arb_puntoreferencia_predio_fkey"),
            "tipo_punto_referencia": _relation("tipo_punto_referencia", "ARB_PuntoReferenciaTipo", "arb_puntoreferencia_tipo_punto_referencia_fkey"),
        },
    ),
    "ARB_Tramite": TableSchema(
        name="ARB_Tramite",
        relations={
            "entidad": _relation("entidad", "ARB_EntidadTipo", "arb_tramite_entidad_fkey"),
            "predio": _relation("predio", "ARB_Predio", "arb_tramite_predio_fkey"),
            "tramite": _relation("tramite", "ARB_TramiteTipo", "arb_tramite_tramite_fkey"),
        },
    ),
    "ARB_MarcaPredial": TableSchema(
        name="ARB_MarcaPredial",
        relations={
            "predio": _relation("predio", "ARB_Predio", "arb_marca_predio_fkey"),
            "marca_tipo": _relation("marca_tipo", "ARB_MarcaPredialTipo", "arb_marca_marca_tipo_fkey"),
        },
    ),
    "ARB_InformacionPH": TableSchema(
        name="ARB_InformacionPH",
        relations={
            "predio": _relation("predio", "ARB_Predio", "arb_informacionph_arb_predio_fkey"),
        },
    ),
}


def get_table_schema(table_name: str) -> TableSchema | None:
    """Devuelve la definición de una tabla operativa si está catalogada."""

    return TABLE_SCHEMAS.get(table_name)


def get_domain_schema(table_name: str) -> TableSchema | None:
    """Devuelve la definición de una tabla de dominios."""

    return DOMAIN_TABLES.get(table_name)


__all__ = [
    "Relation",
    "TableSchema",
    "TABLE_SCHEMAS",
    "DOMAIN_TABLES",
    "get_table_schema",
    "get_domain_schema",
]
