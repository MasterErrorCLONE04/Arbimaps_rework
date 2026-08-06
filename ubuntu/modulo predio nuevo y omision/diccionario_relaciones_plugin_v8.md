# Diccionario de Estructura y Relaciones del Esquema `plugin_v8`

El esquema **`plugin_v8`** dentro de la base de datos **`neiva_castro_registro`** corresponde a la implementación del modelo de datos **LADM-COL** (Land Administration Domain Model - Colombia) generado mediante las herramientas ili2pg e INTERLIS para la gestión del Catastro-Registro.

---

## 📊 Resumen del Esquema `plugin_v8`

- **Total de Tablas**: **116**
- **Total de Relaciones (Foreign Keys)**: **146**
- **Modelo de Referencia**: LADM-COL V4 / V8 (QGIS Plugin)

---

## 🔗 Principales Entidades y Relaciones

### 1. Núcleo Predial y Físico
- **`arb_predio`**: Unidad catastral y registral básica.
  - `arb_terreno.predio` ➔ `arb_predio.t_id`
  - `arb_direccion.predio` ➔ `arb_predio.t_id`
  - `arb_avaluovalor.arb_predio_avaluo` ➔ `arb_predio.t_id`
  - `arb_alertapredio.predio` ➔ `arb_predio.t_id`

### 2. Unidad de Construcción y Características
- **`arb_construccion`**: Estructuras físicas dentro del predio.
- **`arb_unidadconstruccion`**: Unidades funcionales independientes.
  - `arb_unidadconstruccion.arb_construccion_unidadconstruccion` ➔ `arb_construccion.t_id`
  - `arb_caracteristicasunidadconstruccion` ➔ Dominios tipo (`arb_armazontipo`, `arb_cubiertatipo`, `arb_estadoconservaciontipo`, etc.)

### 3. Derechos e Interesados (Legales)
- **`arb_derechointeresadofuente`**: Enlace entre el Predio, la Fuente Jurídica y los Titulares de Derechos.
  - `arb_adjuntointeresadovalor` ➔ `arb_derechointeresadofuente.t_id`
  - `arb_adjuntofuenteadministrativavalor` ➔ `arb_derechointeresadofuente.t_id`

---

## 📋 Catálogo Completo de Relaciones (Foreign Keys) en `plugin_v8`

| Tabla Origen (Child) | Columna Origen | Tabla Destino (Parent) | Columna Destino | Nombre Restricción |
| :--- | :--- | :--- | :--- | :--- |
| `arb_adjuntofuenteadministrativavalor` | `arb_derechointersdfnte_fa_adjunto` | `arb_derechointeresadofuente` | `t_id` | `arb_adjuntofntdmnstrtvvlor_arb_derechntrsdfnt_f_djnto_fkey` |
| `arb_adjuntofuenteadministrativavalor` | `f_documento_soporte_tipo` | `arb_documentosoportetipo` | `t_id` | `arb_adjuntofntdmnstrtvvlor_f_documento_soporte_tipo_fkey` |
| `arb_adjuntofuenteadministrativavalor` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_adjuntofntdmnstrtvvlor_t_basket_fkey` |
| `arb_adjuntointeresadovalor` | `arb_derechointersdfnte_i_adjunto` | `arb_derechointeresadofuente` | `t_id` | `arb_adjuntointeresadovalor_arb_derechontrsdfnt__djnto_fkey` |
| `arb_adjuntointeresadovalor` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_adjuntointeresadovalor_t_basket_fkey` |
| `arb_adjuntopuntoreferenciavalor` | `arb_puntoreferencia_adjunto` | `arb_puntoreferencia` | `t_id` | `arb_adjuntopuntorefrncvlor_arb_puntoreferencia_adjnto_fkey` |
| `arb_adjuntopuntoreferenciavalor` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_adjuntopuntorefrncvlor_t_basket_fkey` |
| `arb_adjuntoterrenovalor` | `arb_terreno_adjunto` | `arb_terreno` | `t_id` | `arb_adjuntoterrenovalor_arb_terreno_adjunto_fkey` |
| `arb_adjuntoterrenovalor` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_adjuntoterrenovalor_t_basket_fkey` |
| `arb_adjuntounidadconstruccionvalor` | `arb_unidadconstruccion_adjunto` | `arb_unidadconstruccion` | `t_id` | `arb_adjuntonddcnstrccnvlor_arb_unidadconstruccn_djnto_fkey` |
| `arb_adjuntounidadconstruccionvalor` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_adjuntonddcnstrccnvlor_t_basket_fkey` |
| `arb_adjuntounidadconstruccionvalor` | `tipo_elemento` | `arb_adjuntoelementotipo` | `t_id` | `arb_adjuntonddcnstrccnvlor_tipo_elemento_fkey` |
| `arb_alertapredio` | `predio` | `arb_predio` | `t_id` | `arb_alertapredio_predio_fkey` |
| `arb_alertapredio` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_alertapredio_t_basket_fkey` |
| `arb_avaluovalor` | `arb_predio_avaluo` | `arb_predio` | `t_id` | `arb_avaluovalor_arb_predio_avaluo_fkey` |
| `arb_avaluovalor` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_avaluovalor_t_basket_fkey` |
| `arb_caracteristicasunidadconstruccion` | `cc_armazon` | `arb_armazontipo` | `t_id` | `arb_crctrstcsnddcnstrccion_cc_armazon_fkey` |
| `arb_caracteristicasunidadconstruccion` | `cc_cerchas_complemento_industria` | `arb_cerchascomplementoindustriatipo` | `t_id` | `arb_crctrstcsnddcnstrccion_cc_cerchas_cmplmnt_ndstria_fkey` |
| `arb_caracteristicasunidadconstruccion` | `cc_conservacion_acabados` | `arb_estadoconservaciontipo` | `t_id` | `arb_crctrstcsnddcnstrccion_cc_conservacion_acabados_fkey` |
| `arb_caracteristicasunidadconstruccion` | `cc_conservacion_banio` | `arb_estadoconservaciontipo` | `t_id` | `arb_crctrstcsnddcnstrccion_cc_conservacion_banio_fkey` |
| `arb_caracteristicasunidadconstruccion` | `cc_conservacion_cocina` | `arb_estadoconservaciontipo` | `t_id` | `arb_crctrstcsnddcnstrccion_cc_conservacion_cocina_fkey` |
| `arb_caracteristicasunidadconstruccion` | `cc_conservacion_estructura` | `arb_estadoconservaciontipo` | `t_id` | `arb_crctrstcsnddcnstrccion_cc_conservacion_estructura_fkey` |
| `arb_caracteristicasunidadconstruccion` | `cc_cubierta` | `arb_cubiertatipo` | `t_id` | `arb_crctrstcsnddcnstrccion_cc_cubierta_fkey` |
| `arb_caracteristicasunidadconstruccion` | `cc_cubrimiento_muros` | `arb_cubrimientomurostipo` | `t_id` | `arb_crctrstcsnddcnstrccion_cc_cubrimiento_muros_fkey` |
| `arb_caracteristicasunidadconstruccion` | `cc_enchape_banio` | `arb_enchapebaniotipo` | `t_id` | `arb_crctrstcsnddcnstrccion_cc_enchape_banio_fkey` |
| `arb_caracteristicasunidadconstruccion` | `cc_enchape_cocina` | `arb_enchapecocinatipo` | `t_id` | `arb_crctrstcsnddcnstrccion_cc_enchape_cocina_fkey` |
| `arb_caracteristicasunidadconstruccion` | `cc_fachada` | `arb_fachadatipo` | `t_id` | `arb_crctrstcsnddcnstrccion_cc_fachada_fkey` |
| `arb_caracteristicasunidadconstruccion` | `cc_mobiliario_banio` | `arb_mobiliariobaniotipo` | `t_id` | `arb_crctrstcsnddcnstrccion_cc_mobiliario_banio_fkey` |
| `arb_caracteristicasunidadconstruccion` | `cc_mobiliario_cocina` | `arb_mobiliariococinatipo` | `t_id` | `arb_crctrstcsnddcnstrccion_cc_mobiliario_cocina_fkey` |
| `arb_caracteristicasunidadconstruccion` | `cc_muros` | `arb_murostipo` | `t_id` | `arb_crctrstcsnddcnstrccion_cc_muros_fkey` |
| `arb_caracteristicasunidadconstruccion` | `cc_piso` | `arb_pisotipo` | `t_id` | `arb_crctrstcsnddcnstrccion_cc_piso_fkey` |
| `arb_caracteristicasunidadconstruccion` | `cc_tamanio_banio` | `arb_tamaniobaniotipo` | `t_id` | `arb_crctrstcsnddcnstrccion_cc_tamanio_banio_fkey` |
| `arb_caracteristicasunidadconstruccion` | `cc_tamanio_cocina` | `arb_tamaniococinatipo` | `t_id` | `arb_crctrstcsnddcnstrccion_cc_tamanio_cocina_fkey` |
| `arb_caracteristicasunidadconstruccion` | `cc_tipo_calificar` | `arb_calificartipo` | `t_id` | `arb_crctrstcsnddcnstrccion_cc_tipo_calificar_fkey` |
| `arb_caracteristicasunidadconstruccion` | `cnc_conservacion_anexo` | `arb_estadoconservaciontipologiatipo` | `t_id` | `arb_crctrstcsnddcnstrccion_cnc_conservacion_anexo_fkey` |
| `arb_caracteristicasunidadconstruccion` | `cnc_tipo_anexo` | `arb_anexotipo` | `t_id` | `arb_crctrstcsnddcnstrccion_cnc_tipo_anexo_fkey` |
| `arb_caracteristicasunidadconstruccion` | `ct_conservacion_tipologia` | `arb_estadoconservaciontipologiatipo` | `t_id` | `arb_crctrstcsnddcnstrccion_ct_conservacion_tipologia_fkey` |
| `arb_caracteristicasunidadconstruccion` | `ct_tipo_tipologia` | `arb_tipologiatipo` | `t_id` | `arb_crctrstcsnddcnstrccion_ct_tipo_tipologia_fkey` |
| `arb_caracteristicasunidadconstruccion` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_crctrstcsnddcnstrccion_t_basket_fkey` |
| `arb_caracteristicasunidadconstruccion` | `tipo_calificacion` | `arb_calificaciontipo` | `t_id` | `arb_crctrstcsnddcnstrccion_tipo_calificacion_fkey` |
| `arb_caracteristicasunidadconstruccion` | `tipo_unidad_construccion` | `arb_unidadconstrucciontipo` | `t_id` | `arb_crctrstcsnddcnstrccion_tipo_unidad_construccion_fkey` |
| `arb_caracteristicasunidadconstruccion` | `uso` | `arb_usouconstipo` | `t_id` | `arb_crctrstcsnddcnstrccion_uso_fkey` |
| `arb_caracteristicasunidadconstruccion` | `usos_tradicionales_culturales` | `arb_usostradicionalesculturalestipo` | `t_id` | `arb_crctrstcsnddcnstrccion_usos_tradicionales_cltrles_fkey` |
| `arb_construccion` | `estado_construccion` | `arb_estadoconstrucciontipo` | `t_id` | `arb_construccion_estado_construccion_fkey` |
| `arb_construccion` | `predio` | `arb_predio` | `t_id` | `arb_construccion_predio_fkey` |
| `arb_construccion` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_construccion_t_basket_fkey` |
| `arb_construccion` | `tipo_construccion` | `arb_tipoconstrucciontipo` | `t_id` | `arb_construccion_tipo_construccion_fkey` |
| `arb_construccion` | `tipo_dominio` | `arb_tipodominioconstrucciontipo` | `t_id` | `arb_construccion_tipo_dominio_fkey` |
| `arb_derechointeresadofuente` | `d_tipo` | `arb_derechotipo` | `t_id` | `arb_derechointeresadofunte_d_tipo_fkey` |
| `arb_derechointeresadofuente` | `fa_tipo` | `arb_fuenteadministrativatipo` | `t_id` | `arb_derechointeresadofunte_fa_tipo_fkey` |
| `arb_derechointeresadofuente` | `i_grupo_etnico` | `arb_grupoetnicotipo` | `t_id` | `arb_derechointeresadofunte_i_grupo_etnico_fkey` |
| `arb_derechointeresadofuente` | `i_sexo` | `arb_sexotipo` | `t_id` | `arb_derechointeresadofunte_i_sexo_fkey` |
| `arb_derechointeresadofuente` | `i_tipo` | `arb_interesadotipo` | `t_id` | `arb_derechointeresadofunte_i_tipo_fkey` |
| `arb_derechointeresadofuente` | `i_tipo_documento` | `arb_interesadodocumentotipo` | `t_id` | `arb_derechointeresadofunte_i_tipo_documento_fkey` |
| `arb_derechointeresadofuente` | `ie_nombre_pueblo` | `arb_nombrepueblosindigenastipo` | `t_id` | `arb_derechointeresadofunte_ie_nombre_pueblo_fkey` |
| `arb_derechointeresadofuente` | `naturaleza_juridica` | `arb_naturalezajuridicatipo` | `t_id` | `arb_derechointeresadofunte_naturaleza_juridica_fkey` |
| `arb_derechointeresadofuente` | `predio` | `arb_predio` | `t_id` | `arb_derechointeresadofunte_predio_fkey` |
| `arb_derechointeresadofuente` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_derechointeresadofunte_t_basket_fkey` |
| `arb_direccion` | `arb_predio_direccion` | `arb_predio` | `t_id` | `arb_direccion_arb_predio_direccion_fkey` |
| `arb_direccion` | `clase_via_principal` | `arb_claseviaprincipaltipo` | `t_id` | `arb_direccion_clase_via_principal_fkey` |
| `arb_direccion` | `sector_ciudad` | `arb_sectortipo` | `t_id` | `arb_direccion_sector_ciudad_fkey` |
| `arb_direccion` | `sector_predio` | `arb_sectortipo` | `t_id` | `arb_direccion_sector_predio_fkey` |
| `arb_direccion` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_direccion_t_basket_fkey` |
| `arb_direccion` | `tipo_direccion` | `arb_direcciontipo` | `t_id` | `arb_direccion_tipo_direccion_fkey` |
| `arb_estructuramatriculamatriz` | `predio` | `arb_predio` | `t_id` | `arb_estructuramatriclmtriz_predio_fkey` |
| `arb_estructuramatriculamatriz` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_estructuramatriclmtriz_t_basket_fkey` |
| `arb_estructuramatriculasegregados` | `predio` | `arb_predio` | `t_id` | `arb_estructuramtrclsgrgdos_predio_fkey` |
| `arb_estructuramatriculasegregados` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_estructuramtrclsgrgdos_t_basket_fkey` |
| `arb_estructuraprediomatriznpn` | `predio` | `arb_predio` | `t_id` | `arb_estructurapredimtrznpn_predio_fkey` |
| `arb_estructuraprediomatriznpn` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_estructurapredimtrznpn_t_basket_fkey` |
| `arb_estructurapredioorigennpn` | `predio` | `arb_predio` | `t_id` | `arb_estructuraprediorgnnpn_predio_fkey` |
| `arb_estructurapredioorigennpn` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_estructuraprediorgnnpn_t_basket_fkey` |
| `arb_hipoteca` | `predio` | `arb_predio` | `t_id` | `arb_hipoteca_predio_fkey` |
| `arb_hipoteca` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_hipoteca_t_basket_fkey` |
| `arb_hipoteca` | `tipo_hipoteca` | `arb_tipohipotecatipo` | `t_id` | `arb_hipoteca_tipo_hipoteca_fkey` |
| `arb_informacionph` | `arb_predio` | `arb_predio` | `t_id` | `arb_informacionph_arb_predio_fkey` |
| `arb_informacionph` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_informacionph_t_basket_fkey` |
| `arb_informalidad` | `predio` | `arb_predio` | `t_id` | `arb_informalidad_predio_fkey` |
| `arb_informalidad` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_informalidad_t_basket_fkey` |
| `arb_informalidad` | `tipo_informalidad` | `arb_tipoinformalidadtipo` | `t_id` | `arb_informalidad_tipo_informalidad_fkey` |
| `arb_lindero` | `predio` | `arb_predio` | `t_id` | `arb_lindero_predio_fkey` |
| `arb_lindero` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_lindero_t_basket_fkey` |
| `arb_marca` | `marca_tipo` | `arb_marcapredialtipo` | `t_id` | `arb_marca_marca_tipo_fkey` |
| `arb_marca` | `predio` | `arb_predio` | `t_id` | `arb_marca_predio_fkey` |
| `arb_marca` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_marca_t_basket_fkey` |
| `arb_novedadfmivalor` | `arb_predio_novedad_fmi` | `arb_predio` | `t_id` | `arb_novedadfmivalor_arb_predio_novedad_fmi_fkey` |
| `arb_novedadfmivalor` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_novedadfmivalor_t_basket_fkey` |
| `arb_novedadfmivalor` | `tipo_novedad_fmi` | `arb_novedadfmitipo` | `t_id` | `arb_novedadfmivalor_tipo_novedad_fmi_fkey` |
| `arb_novedadnumeropredialvalor` | `arb_predio_novedad_numero_predial` | `arb_predio` | `t_id` | `arb_novedadnumeropredlvlor_arb_predio_nvdd_nmr_prdial_fkey` |
| `arb_novedadnumeropredialvalor` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_novedadnumeropredlvlor_t_basket_fkey` |
| `arb_novedadnumeropredialvalor` | `tipo_novedad` | `arb_novedadnumeropredialtipo` | `t_id` | `arb_novedadnumeropredlvlor_tipo_novedad_fkey` |
| `arb_predio` | `condicion_predio` | `arb_condicionprediotipo` | `t_id` | `arb_predio_condicion_predio_fkey` |
| `arb_predio` | `destinacion_economica` | `arb_destinacioneconomicatipo` | `t_id` | `arb_predio_destinacion_economica_fkey` |
| `arb_predio` | `estado` | `arb_estadotipo` | `t_id` | `arb_predio_estado_fkey` |
| `arb_predio` | `estado_fmi` | `arb_estadofmitipo` | `t_id` | `arb_predio_estado_fmi_fkey` |
| `arb_predio` | `resultado_visita` | `arb_resultadovisitatipo` | `t_id` | `arb_predio_resultado_visita_fkey` |
| `arb_predio` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_predio_t_basket_fkey` |
| `arb_predio` | `tipo` | `arb_prediotipo` | `t_id` | `arb_predio_tipo_fkey` |
| `arb_predio` | `tipo_captura` | `arb_metodoproducciontipo` | `t_id` | `arb_predio_tipo_captura_fkey` |
| `arb_predio` | `tipo_documento_quien_atendio` | `arb_interesadodocumentotipo` | `t_id` | `arb_predio_tipo_documento_quien_tndio_fkey` |
| `arb_predio_tramite` | `predio` | `arb_predio` | `t_id` | `arb_predio_tramite_predio_fkey` |
| `arb_predio_tramite` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_predio_tramite_t_basket_fkey` |
| `arb_predio_tramite` | `tramite` | `arb_tramite` | `t_id` | `arb_predio_tramite_tramite_fkey` |
| `arb_publicidad` | `predio` | `arb_predio` | `t_id` | `arb_publicidad_predio_fkey` |
| `arb_publicidad` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_publicidad_t_basket_fkey` |
| `arb_publicidad` | `tipo_publicidad` | `arb_publicidadtipo` | `t_id` | `arb_publicidad_tipo_publicidad_fkey` |
| `arb_puntocontrol` | `predio` | `arb_predio` | `t_id` | `arb_puntocontrol_predio_fkey` |
| `arb_puntocontrol` | `puntotipo` | `arb_puntotipo` | `t_id` | `arb_puntocontrol_puntotipo_fkey` |
| `arb_puntocontrol` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_puntocontrol_t_basket_fkey` |
| `arb_puntocontrol` | `tipo_punto_control` | `arb_puntocontroltipo` | `t_id` | `arb_puntocontrol_tipo_punto_control_fkey` |
| `arb_puntolindero` | `fotoidentificacion` | `arb_fotoidentificaciontipo` | `t_id` | `arb_puntolindero_fotoidentificacion_fkey` |
| `arb_puntolindero` | `lindero` | `arb_lindero` | `t_id` | `arb_puntolindero_lindero_fkey` |
| `arb_puntolindero` | `puntotipo` | `arb_puntolinderotipo` | `t_id` | `arb_puntolindero_puntotipo_fkey` |
| `arb_puntolindero` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_puntolindero_t_basket_fkey` |
| `arb_puntoreferencia` | `predio` | `arb_predio` | `t_id` | `arb_puntoreferencia_predio_fkey` |
| `arb_puntoreferencia` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_puntoreferencia_t_basket_fkey` |
| `arb_puntoreferencia` | `tipo_punto_referencia` | `arb_puntoreferenciatipo` | `t_id` | `arb_puntoreferencia_tipo_punto_referencia_fkey` |
| `arb_referenciaregistralsistemaantiguovalor` | `arb_predio_referencia_registral_sistema_antiguo` | `arb_predio` | `t_id` | `arb_rfrncrgstrlsstmntgvlor_arb_prd_rfrncrl_sstm_ntguo_fkey` |
| `arb_referenciaregistralsistemaantiguovalor` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_rfrncrgstrlsstmntgvlor_t_basket_fkey` |
| `arb_referenciaregistralsistemaantiguovalor` | `tipo_referencia` | `arb_referenciatipo` | `t_id` | `arb_rfrncrgstrlsstmntgvlor_tipo_referencia_fkey` |
| `arb_restriccion` | `predio` | `arb_predio` | `t_id` | `arb_restriccion_predio_fkey` |
| `arb_restriccion` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_restriccion_t_basket_fkey` |
| `arb_restriccion` | `tipo_restriccion` | `arb_tipohipotecatipo` | `t_id` | `arb_restriccion_tipo_restriccion_fkey` |
| `arb_terreno` | `estado_terreno` | `arb_estadoterrenotipo` | `t_id` | `arb_terreno_estado_terreno_fkey` |
| `arb_terreno` | `predio` | `arb_predio` | `t_id` | `arb_terreno_predio_fkey` |
| `arb_terreno` | `relacion_superficie` | `arb_relacionsuperficieterrenotipo` | `t_id` | `arb_terreno_relacion_superficie_fkey` |
| `arb_terreno` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_terreno_t_basket_fkey` |
| `arb_terrenohistorico` | `predio` | `arb_predio` | `t_id` | `arb_terrenohistorico_predio_fkey` |
| `arb_terrenohistorico` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_terrenohistorico_t_basket_fkey` |
| `arb_tramite` | `clasificacion_mutacion` | `arb_clasificacionmutaciontipo` | `t_id` | `arb_tramite_clasificacion_mutacion_fkey` |
| `arb_tramite` | `entidad` | `arb_entidadtipo` | `t_id` | `arb_tramite_entidad_fkey` |
| `arb_tramite` | `subtipo_mutacion` | `arb_subtipomutaciontipo` | `t_id` | `arb_tramite_subtipo_mutacion_fkey` |
| `arb_tramite` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_tramite_t_basket_fkey` |
| `arb_tramite` | `tipo_mutacion` | `arb_tipomutaciontipo` | `t_id` | `arb_tramite_tipo_mutacion_fkey` |
| `arb_tramite` | `tipo_tramite` | `arb_tipotramitetipo` | `t_id` | `arb_tramite_tipo_tramite_fkey` |
| `arb_tramite` | `tramite` | `arb_tramitetipo` | `t_id` | `arb_tramite_tramite_fkey` |
| `arb_unidadconstruccion` | `caracteristicasunidadconstruccion` | `arb_caracteristicasunidadconstruccion` | `t_id` | `arb_unidadconstruccion_caracteristcsnddcnstrccion_fkey` |
| `arb_unidadconstruccion` | `construccion` | `arb_construccion` | `t_id` | `arb_unidadconstruccion_construccion_fkey` |
| `arb_unidadconstruccion` | `estado_unidad_construccion` | `arb_estadoconstrucciontipo` | `t_id` | `arb_unidadconstruccion_estado_unidad_construccion_fkey` |
| `arb_unidadconstruccion` | `relacion_superficie` | `arb_relacionsuperficieconstrucciontipo` | `t_id` | `arb_unidadconstruccion_relacion_superficie_fkey` |
| `arb_unidadconstruccion` | `t_basket` | `t_ili2db_basket` | `t_id` | `arb_unidadconstruccion_t_basket_fkey` |
| `arb_unidadconstruccion` | `tipo_planta` | `arb_construccionplantatipo` | `t_id` | `arb_unidadconstruccion_tipo_planta_fkey` |
| `gm_multisurface2d` | `t_basket` | `t_ili2db_basket` | `t_id` | `gm_multisurface2d_t_basket_fkey` |
| `gm_surface2dlistvalue` | `gm_multisurface2d_geometry` | `gm_multisurface2d` | `t_id` | `gm_surface2dlistvalue_gm_multisurface2d_geometry_fkey` |
| `gm_surface2dlistvalue` | `t_basket` | `t_ili2db_basket` | `t_id` | `gm_surface2dlistvalue_t_basket_fkey` |
| `t_ili2db_basket` | `dataset` | `t_ili2db_dataset` | `t_id` | `t_ili2db_basket_dataset_fkey` |

---

## 🗄️ Resumen de Filas por Tabla en `plugin_v8`

| Tabla | Filas Registradas | Total Columnas |
| :--- | :---: | :---: |
| `arb_adjuntoelementotipo` | **9** | 9 |
| `arb_adjuntofuenteadministrativavalor` | **0** | 9 |
| `arb_adjuntointeresadovalor` | **0** | 8 |
| `arb_adjuntopuntoreferenciavalor` | **0** | 8 |
| `arb_adjuntoterrenovalor` | **0** | 8 |
| `arb_adjuntounidadconstruccionvalor` | **0** | 9 |
| `arb_alertapredio` | **0** | 8 |
| `arb_anexotipo` | **108** | 9 |
| `arb_armazontipo` | **5** | 9 |
| `arb_avaluovalor` | **3,330,744** | 13 |
| `arb_calificaciontipo` | **3** | 9 |
| `arb_calificartipo` | **3** | 9 |
| `arb_caracteristicasunidadconstruccion` | **15,301** | 41 |
| `arb_cerchascomplementoindustriatipo` | **4** | 9 |
| `arb_claseviaprincipaltipo` | **10** | 9 |
| `arb_clasificacionmutaciontipo` | **24** | 9 |
| `arb_codigonaturalezajuridicatipo` | **449** | 9 |
| `arb_condicionprediotipo` | **10** | 9 |
| `arb_construccion` | **146,963** | 16 |
| `arb_construccionplantatipo` | **5** | 9 |
| `arb_cubiertatipo` | **6** | 9 |
| `arb_cubrimientomurostipo` | **5** | 9 |
| `arb_derechointeresadofuente` | **147,457** | 43 |
| `arb_derechotipo` | **3** | 9 |
| `arb_destinacioneconomicatipo` | **31** | 9 |
| `arb_direccion` | **166,471** | 19 |
| `arb_direcciontipo` | **2** | 9 |
| `arb_documentosoportetipo` | **5** | 9 |
| `arb_enchapebaniotipo` | **6** | 9 |
| `arb_enchapecocinatipo` | **6** | 9 |
| `arb_entidadtipo` | **3** | 9 |
| `arb_estadoconservaciontipo` | **4** | 9 |
| `arb_estadoconservaciontipologiatipo` | **9** | 9 |
| `arb_estadoconstrucciontipo` | **2** | 9 |
| `arb_estadofmitipo` | **2** | 9 |
| `arb_estadoterrenotipo` | **2** | 9 |
| `arb_estadotipo` | **2** | 9 |
| `arb_estructuramatriculamatriz` | **6** | 6 |
| `arb_estructuramatriculasegregados` | **147** | 6 |
| `arb_estructuraprediomatriznpn` | **9** | 6 |
| `arb_estructurapredioorigennpn` | **0** | 6 |
| `arb_fachadatipo` | **5** | 9 |
| `arb_fotoidentificaciontipo` | **2** | 9 |
| `arb_fuenteadministrativatipo` | **13** | 9 |
| `arb_grupoetnicotipo` | **6** | 9 |
| `arb_hipoteca` | **0** | 9 |
| `arb_informacionph` | **36,307** | 15 |
| `arb_informalidad` | **15,091** | 9 |
| `arb_interesadodocumentotipo` | **7** | 9 |
| `arb_interesadotipo` | **2** | 9 |
| `arb_lindero` | **0** | 6 |
| `arb_marca` | **0** | 10 |
| `arb_marcapredialtipo` | **49** | 9 |
| `arb_metodoproducciontipo` | **3** | 9 |
| `arb_mobiliariobaniotipo` | **5** | 9 |
| `arb_mobiliariococinatipo` | **5** | 9 |
| `arb_murostipo` | **5** | 9 |
| `arb_naturalezajuridicatipo` | **449** | 9 |
| `arb_nombrepueblosindigenastipo` | **127** | 9 |
| `arb_novedadfmitipo` | **7** | 9 |
| `arb_novedadfmivalor` | **0** | 8 |
| `arb_novedadnumeropredialtipo` | **23** | 9 |
| `arb_novedadnumeropredialvalor` | **0** | 7 |
| `arb_pisotipo` | **7** | 9 |
| `arb_predio` | **166,372** | 43 |
| `arb_predio_tramite` | **8,228** | 4 |
| `arb_prediotipo` | **7** | 9 |
| `arb_publicidad` | **0** | 10 |
| `arb_publicidadtipo` | **5** | 9 |
| `arb_puntocontrol` | **0** | 9 |
| `arb_puntocontroltipo` | **2** | 9 |
| `arb_puntolindero` | **0** | 12 |
| `arb_puntolinderotipo` | **3** | 9 |
| `arb_puntoreferencia` | **0** | 7 |
| `arb_puntoreferenciatipo` | **7** | 9 |
| `arb_puntotipo` | **9** | 9 |
| `arb_referenciaregistralsistemaantiguovalor` | **0** | 15 |
| `arb_referenciatipo` | **2** | 9 |
| `arb_relacionsuperficieconstrucciontipo` | **4** | 9 |
| `arb_relacionsuperficieterrenotipo` | **4** | 9 |
| `arb_restriccion` | **0** | 9 |
| `arb_resultadovisitatipo` | **8** | 9 |
| `arb_sectortipo` | **4** | 9 |
| `arb_sexotipo` | **3** | 9 |
| `arb_subtipomutaciontipo` | **16** | 9 |
| `arb_tamaniobaniotipo` | **4** | 9 |
| `arb_tamaniococinatipo` | **4** | 9 |
| `arb_terreno` | **102,348** | 9 |
| `arb_terrenohistorico` | **0** | 7 |
| `arb_tipoconstrucciontipo` | **2** | 9 |
| `arb_tipodominioconstrucciontipo` | **2** | 9 |
| `arb_tipohipotecatipo` | **9** | 9 |
| `arb_tipoinformalidadtipo` | **2** | 9 |
| `arb_tipologiatipo` | **52** | 9 |
| `arb_tipomutaciontipo` | **5** | 9 |
| `arb_tipotramitetipo` | **9** | 9 |
| `arb_tramite` | **9,496** | 36 |
| `arb_tramitetipo` | **16** | 9 |
| `arb_unidadconstruccion` | **19,546** | 15 |
| `arb_unidadconstrucciontipo` | **6** | 9 |
| `arb_usostradicionalesculturalestipo` | **25** | 9 |
| `arb_usouconstipo` | **102** | 9 |
| `gm_multisurface2d` | **0** | 4 |
| `gm_surface2dlistvalue` | **0** | 6 |
| `t_ili2db_attrname` | **337** | 4 |
| `t_ili2db_basket` | **1** | 6 |
| `t_ili2db_classname` | **125** | 2 |
| `t_ili2db_column_prop` | **950** | 5 |
| `t_ili2db_dataset` | **1** | 2 |
| `t_ili2db_inheritance` | **57** | 2 |
| `t_ili2db_meta_attrs` | **1,380** | 3 |
| `t_ili2db_model` | **2** | 5 |
| `t_ili2db_settings` | **27** | 2 |
| `t_ili2db_table_prop` | **137** | 3 |
| `t_ili2db_trafo` | **61** | 3 |
| `tmp_tramites_csv` | **3,202** | 8 |
