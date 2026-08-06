# Módulo Predio Nuevo y Omisión (Panel de Asignación LADM-COL)

Este paquete contiene todos los módulos Python, scripts ETL y consultas SQL necesarios para integrar la funcionalidad de **Asignación Predial, Predios Nuevos u Omisiones** dentro del Backend de la aplicación.

---

## 📁 Contenido de la Carpeta

```
modulo predio nuevo y omision/
├── service_asignacion_predial.py           <-- MÓDULO BACKEND PRINCIPAL (Geo + Alfa -> b_asignaciones_arb -> XTF)
├── etl_transfer_predio_b_asignaciones.py    <-- Motor ETL de transferencia selectiva por NPN
├── etl_migracion_r1_r2.py                  <-- Script de importación y limpieza de insumos Alfa (R1 / R2)
├── update_dummy_geometries_and_caracteristicas.py <-- Asignación de geometrías EPSG:9377 y bloques R2
├── migrate_propietarios.py                 <-- Migración de propietarios e interesados R1
├── config.env                               <-- Variables de entorno y conexión a PostgreSQL
├── diccionario_relaciones_plugin_v8.md      <-- Diccionario de 116 tablas y 146 relaciones LADM-COL
└── sql/
    ├── 01_create_schema_f_r1_r2.sql        <-- DDL del esquema alfanumérico f_r1_r2
    ├── 02_relacion_r1_r2_views.sql         <-- Vistas relacionales de cruce NPN
    └── 03_consulta_relaciones_plugin_v8.sql<-- Consultas de inspección LADM-COL
```

---

## ⚙️ Flujo de Asignación en el Backend

1. **Rastreo Geo (`a_base_principal`)**: El servicio consulta la geometría del lote/terreno y construcciones en la base gráfica `a_base_principal`.
2. **Rastreo Alfa (Fallback en `f_r1_r2`)**: Si el NPN no cuenta con geometría gráfica inicial, se extrae toda la información catastral alfanumérica desde `f_r1_r2` (R1 y R2).
3. **Poblado LADM-COL (`b_asignaciones_arb`)**: Transfiere los datos a las tablas estándar:
   - `arb_predio`
   - `arb_terreno` (con geometría real o dummy EPSG:9377 para QGIS)
   - `arb_direccion`
   - `arb_avaluovalor`
   - `arb_construccion` (con geometría real o dummy EPSG:9377 para QGIS)
   - `arb_derechointeresadofuente` (Propietarios, Cédulas/NIT y %)
   - `arb_unidadconstruccion` y `arb_caracteristicasunidadconstruccion` (Detalle de Bloques 1, 2 y 3)
4. **Exportación XTF**: Generación de archivo INTERLIS mediante `ili2pg`.

---

## 💻 Ejemplo de Integración en Código (API Backend)

```python
from service_asignacion_predial import AsignadorPredialBackend

# Instanciar servicio
asignador = AsignadorPredialBackend()

# Lista de NPNs enviada desde el Panel de Asignación (Frontend)
lista_npn = ["410010001000000010017000000000"]

# Ejecutar asignación y exportación XTF
asignador.ejecutar_asignacion(
    lista_npn=lista_npn,
    exportar_xtf=True,
    ruta_xtf="exports/asignacion_001.xtf"
)
```
