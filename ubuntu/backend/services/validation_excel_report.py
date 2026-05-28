from __future__ import annotations

import re
from collections import OrderedDict
from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape, quoteattr
from zipfile import ZIP_DEFLATED, ZipFile


HEADERS = ("Componente", "ID", "Capa", "Error", "Descripcion")
MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def build_validation_errors_excel(report: dict[str, Any]) -> bytes:
    sheets = _sheets_for_report(report)
    buffer = BytesIO()

    with ZipFile(buffer, "w", ZIP_DEFLATED) as workbook:
        workbook.writestr("[Content_Types].xml", _content_types_xml(len(sheets)))
        workbook.writestr("_rels/.rels", _root_relationships_xml())
        workbook.writestr("docProps/core.xml", _core_properties_xml(report))
        workbook.writestr("docProps/app.xml", _app_properties_xml())
        workbook.writestr("xl/workbook.xml", _workbook_xml(sheets))
        workbook.writestr("xl/_rels/workbook.xml.rels", _workbook_relationships_xml(len(sheets)))
        workbook.writestr("xl/styles.xml", _styles_xml())

        for index, sheet in enumerate(sheets, start=1):
            workbook.writestr(
                f"xl/worksheets/sheet{index}.xml",
                _worksheet_xml(sheet["rows"]),
            )

    return buffer.getvalue()


def validation_excel_filename(report: dict[str, Any]) -> str:
    raw_date = str(report.get("generated_at") or "").strip()
    generated_at: datetime | None = None
    if raw_date:
        try:
            generated_at = datetime.fromisoformat(raw_date)
        except ValueError:
            generated_at = None
    if generated_at is None:
        generated_at = datetime.now()
    return f"Usuario_errores_validacion_{generated_at:%Y%m%d_%H%M}.xlsx"


def _sheets_for_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _error_rows(report)
    if not rows:
        rows = [
            {
                "component": "Sin componente",
                "id": "",
                "layer": "",
                "error": "",
                "description": "No hay errores para exportar.",
            }
        ]

    sheets: list[dict[str, Any]] = []
    used_names: set[str] = set()

    sheets.append(
        {
            "name": _safe_sheet_name("Consolidado", used_names),
            "rows": [_row_values(row) for row in rows],
        }
    )

    grouped: "OrderedDict[str, list[dict[str, str]]]" = OrderedDict()
    for row in rows:
        component = row["component"] or "Sin componente"
        grouped.setdefault(component, []).append(row)

    for component, component_rows in grouped.items():
        sheets.append(
            {
                "name": _safe_sheet_name(component, used_names),
                "rows": [_row_values(row) for row in component_rows],
            }
        )

    return sheets


def _error_rows(report: dict[str, Any]) -> list[dict[str, str]]:
    validation = report.get("validation") or {}
    quality = validation.get("quality") or {}
    catalog = quality.get("rule_catalog") or {}
    rule_meta_by_id = _rule_meta_by_id(quality)
    rows: list[dict[str, str]] = []

    for item in _as_list(validation.get("rule_errors")):
        if not isinstance(item, dict):
            continue

        rule_id = _clean_text(item.get("rule") or item.get("rule_id") or "No disponible")
        rule_meta = rule_meta_by_id.get(rule_id, {})
        catalog_item = catalog.get(rule_id) if isinstance(catalog, dict) else {}
        if not isinstance(catalog_item, dict):
            catalog_item = {}

        component = _clean_text(
            item.get("component_label")
            or rule_meta.get("component_label")
            or catalog_item.get("component_label")
            or item.get("component")
            or rule_meta.get("component")
            or catalog_item.get("component_slug")
            or "Sin componente"
        )
        description = _clean_text(
            item.get("message")
            or item.get("description")
            or item.get("descripcion")
            or rule_meta.get("description")
            or catalog_item.get("description")
            or "Sin detalle adicional"
        )

        rows.append(
            {
                "component": component,
                "id": _clean_text(
                    item.get("display_id")
                    or item.get("object_id")
                    or item.get("tid")
                    or "Sin identificar"
                ),
                "layer": _clean_text(
                    item.get("object_class")
                    or item.get("class")
                    or item.get("tabla")
                    or "Clase no declarada"
                ),
                "error": rule_id,
                "description": description,
            }
        )

    for item in _as_list(validation.get("schema_errors")):
        if not isinstance(item, dict):
            continue

        rows.append(
            {
                "component": "Estructural XTF",
                "id": _clean_text(
                    item.get("display_id")
                    or item.get("object_id")
                    or item.get("tid")
                    or "Sin identificar"
                ),
                "layer": _clean_text(item.get("object_class") or "Clase no declarada"),
                "error": _clean_text(item.get("rule") or "Estructural"),
                "description": _clean_text(item.get("message") or "Sin detalle adicional"),
            }
        )

    return rows


def _rule_meta_by_id(quality: dict[str, Any]) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for item in _as_list(quality.get("rules")):
        if not isinstance(item, dict):
            continue
        rule_id = _clean_text(item.get("rule") or item.get("rule_id"))
        if rule_id:
            metadata[rule_id] = item
    return metadata


def _row_values(row: dict[str, str]) -> list[str]:
    return [
        row["component"],
        row["id"],
        row["layer"],
        row["error"],
        row["description"],
    ]


def _worksheet_xml(rows: list[list[str]]) -> str:
    all_rows = [list(HEADERS), *rows]
    row_xml = []
    for row_number, values in enumerate(all_rows, start=1):
        cells = [
            _cell_xml(row_number, column_number, value, style=1 if row_number == 1 else 2)
            for column_number, value in enumerate(values, start=1)
        ]
        row_xml.append(f'<row r="{row_number}">{"".join(cells)}</row>')

    last_row = max(len(all_rows), 1)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        "</sheetView></sheetViews>"
        '<sheetFormatPr defaultRowHeight="18"/>'
        '<cols>'
        '<col min="1" max="1" width="22" customWidth="1"/>'
        '<col min="2" max="2" width="26" customWidth="1"/>'
        '<col min="3" max="3" width="34" customWidth="1"/>'
        '<col min="4" max="4" width="18" customWidth="1"/>'
        '<col min="5" max="5" width="72" customWidth="1"/>'
        '</cols>'
        f'<sheetData>{"".join(row_xml)}</sheetData>'
        f'<autoFilter ref="A1:E{last_row}"/>'
        "</worksheet>"
    )


def _cell_xml(row_number: int, column_number: int, value: Any, *, style: int) -> str:
    cell_ref = f"{_column_letter(column_number)}{row_number}"
    text = _clean_text(value)
    space = ' xml:space="preserve"' if text != text.strip() or "\n" in text else ""
    return (
        f'<c r="{cell_ref}" t="inlineStr" s="{style}">'
        f"<is><t{space}>{escape(text)}</t></is>"
        "</c>"
    )


def _content_types_xml(sheet_count: int) -> str:
    sheet_overrides = "".join(
        '<Override PartName="/xl/worksheets/sheet{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'.format(
            index=index
        )
        for index in range(1, sheet_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/docProps/core.xml" '
        'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        f"{sheet_overrides}"
        "</Types>"
    )


def _root_relationships_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
        'Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" '
        'Target="docProps/app.xml"/>'
        "</Relationships>"
    )


def _workbook_xml(sheets: list[dict[str, Any]]) -> str:
    sheet_entries = "".join(
        f'<sheet name={quoteattr(sheet["name"])} sheetId="{index}" r:id="rId{index}"/>'
        for index, sheet in enumerate(sheets, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheet_entries}</sheets>"
        "</workbook>"
    )


def _workbook_relationships_xml(sheet_count: int) -> str:
    sheet_relationships = "".join(
        '<Relationship Id="rId{index}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet{index}.xml"/>'.format(index=index)
        for index in range(1, sheet_count + 1)
    )
    styles_id = sheet_count + 1
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{sheet_relationships}"
        f'<Relationship Id="rId{styles_id}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
        "</Relationships>"
    )


def _styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2">'
        '<font><sz val="11"/><color rgb="FF000000"/><name val="Calibri"/><family val="2"/></font>'
        '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/><family val="2"/></font>'
        '</fonts>'
        '<fills count="3">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF0B3A67"/><bgColor indexed="64"/></patternFill></fill>'
        '</fills>'
        '<borders count="2">'
        '<border><left/><right/><top/><bottom/><diagonal/></border>'
        '<border>'
        '<left style="thin"><color rgb="FFD8E3F0"/></left>'
        '<right style="thin"><color rgb="FFD8E3F0"/></right>'
        '<top style="thin"><color rgb="FFD8E3F0"/></top>'
        '<bottom style="thin"><color rgb="FFD8E3F0"/></bottom>'
        '<diagonal/>'
        '</border>'
        '</borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="3">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1">'
        '<alignment vertical="center"/>'
        '</xf>'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1">'
        '<alignment wrapText="1" vertical="top"/>'
        '</xf>'
        '</cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    )


def _core_properties_xml(report: dict[str, Any]) -> str:
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    filename = _clean_text(report.get("original_filename") or "Validacion XTF")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>Errores de validacion XTF - {escape(filename)}</dc:title>"
        "<dc:creator>ArbiMaps</dc:creator>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{created_at}</dcterms:created>'
        "</cp:coreProperties>"
    )


def _app_properties_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        "<Application>ArbiMaps</Application>"
        "</Properties>"
    )


def _column_letter(column_number: int) -> str:
    letters = ""
    while column_number:
        column_number, remainder = divmod(column_number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _safe_sheet_name(raw_name: str, used_names: set[str]) -> str:
    clean = _clean_text(raw_name)
    clean = re.sub(r"[\[\]\*:/\\?]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip().strip("'") or "Hoja"

    base = clean[:31]
    candidate = base
    counter = 2
    while candidate in used_names:
        suffix = f" ({counter})"
        candidate = f"{base[:31 - len(suffix)]}{suffix}"
        counter += 1

    used_names.add(candidate)
    return candidate


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    return "".join(
        char if char in {"\t", "\n"} or ord(char) >= 32 else " "
        for char in text
    )
