from __future__ import annotations

import json
import os
import re
from collections import OrderedDict
from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape, quoteattr
from zipfile import ZIP_DEFLATED, ZipFile

HEADERS = ("Componente", "ID", "NPN", "Capa", "Error", "Descripcion")
MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

STANDARD_MODULES = [
    {"slug": "administrativo", "label": "Administrativo"},
    {"slug": "juridico", "label": "Juridico"},
    {"slug": "fisico", "label": "Fisico"},
    {"slug": "economico", "label": "Economico"},
    {"slug": "topologico", "label": "Topologico"},
    {"slug": "novedades", "label": "Novedades"},
    {"slug": "estructura", "label": "Estructura"},
    {"slug": "complementarias", "label": "Complementarias"},
    {"slug": "obligatorias", "label": "Obligatorias"},
]


def _normalize_module_slug(raw: str | None) -> str:
    if not raw:
        return "otros"
    s = str(raw).strip().lower()
    s = (
        s.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
    )
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    if "admin" in s:
        return "administrativo"
    if "jurid" in s:
        return "juridico"
    if "fisi" in s:
        return "fisico"
    if "econ" in s:
        return "economico"
    if "topo" in s:
        return "topologico"
    if "noved" in s:
        return "novedades"
    if "estruct" in s:
        return "estructura"
    if "complem" in s:
        return "complementarias"
    if "obligat" in s:
        return "obligatorias"
    return s


def _format_date(raw_date: Any) -> str:
    if not raw_date:
        return datetime.now().strftime("%d/%m/%Y %H:%M")
    try:
        raw_str = str(raw_date).strip()
        dt = datetime.fromisoformat(raw_str)
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(raw_date)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    return "".join(
        char if char in {"\t", "\n"} or ord(char) >= 32 else " "
        for char in text
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
                "npn": _npn_for_item(item),
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
                "component": "Estructura",
                "npn": _npn_for_item(item),
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


def _npn_for_item(item: dict[str, Any]) -> str:
    details = item.get("details")
    if not isinstance(details, dict):
        details = {}
    return _clean_text(
        item.get("npn")
        or details.get("npn")
        or details.get("numero_predial")
        or details.get("numero_predial_nacional")
    )


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
        row["npn"],
        row["layer"],
        row["error"],
        row["description"],
    ]


def _cell_xml(row_number: int, column_number: int, value: Any, *, style: int) -> str:
    cell_ref = f"{_column_letter(column_number)}{row_number}"
    text = _clean_text(value)
    space = ' xml:space="preserve"' if text != text.strip() or "\n" in text else ""
    return (
        f'<c r="{cell_ref}" t="inlineStr" s="{style}">'
        f"<is><t{space}>{escape(text)}</t></is>"
        "</c>"
    )


def _cell_number_xml(row_number: int, column_number: int, number_value: int, *, style: int) -> str:
    cell_ref = f"{_column_letter(column_number)}{row_number}"
    return (
        f'<c r="{cell_ref}" s="{style}">'
        f"<v>{number_value}</v>"
        "</c>"
    )


def _styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="9">'
        '<!-- 0: Regular Calibri 11pt Black -->'
        '<font><sz val="11"/><color rgb="FF000000"/><name val="Calibri"/><family val="2"/></font>'
        '<!-- 1: Bold Calibri 11pt White -->'
        '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/><family val="2"/></font>'
        '<!-- 2: Bold Calibri 14pt Dark Green -->'
        '<font><b/><sz val="14"/><color rgb="FF0A2C1B"/><name val="Calibri"/><family val="2"/></font>'
        '<!-- 3: Italic Calibri 10pt Grey -->'
        '<font><i/><sz val="10"/><color rgb="FF5F6368"/><name val="Calibri"/><family val="2"/></font>'
        '<!-- 4: Bold Calibri 11pt Dark Red -->'
        '<font><b/><sz val="11"/><color rgb="FFC5221F"/><name val="Calibri"/><family val="2"/></font>'
        '<!-- 5: Bold Calibri 11pt Dark Green -->'
        '<font><b/><sz val="11"/><color rgb="FF137333"/><name val="Calibri"/><family val="2"/></font>'
        '<!-- 6: Regular Calibri 10pt Grey -->'
        '<font><sz val="10"/><color rgb="FF70757A"/><name val="Calibri"/><family val="2"/></font>'
        '<!-- 7: Bold Calibri 11pt Black -->'
        '<font><b/><sz val="11"/><color rgb="FF000000"/><name val="Calibri"/><family val="2"/></font>'
        '<!-- 8: Underline Calibri 10pt Dark Green (Link) -->'
        '<font><u/><sz val="10"/><color rgb="FF0A2C1B"/><name val="Calibri"/><family val="2"/></font>'
        '</fonts>'
        '<fills count="7">'
        '<!-- 0: none -->'
        '<fill><patternFill patternType="none"/></fill>'
        '<!-- 1: gray125 -->'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<!-- 2: Dark Green #0A2C1B -->'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF0A2C1B"/><bgColor indexed="64"/></patternFill></fill>'
        '<!-- 3: Light Red #FCE8E6 -->'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFFCE8E6"/><bgColor indexed="64"/></patternFill></fill>'
        '<!-- 4: Light Green #E6F4EA -->'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFE6F4EA"/><bgColor indexed="64"/></patternFill></fill>'
        '<!-- 5: Soft Total BG #EAF2ED -->'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFEAF2ED"/><bgColor indexed="64"/></patternFill></fill>'
        '<!-- 6: Alternating Row #F8FAF9 -->'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFF8FAF9"/><bgColor indexed="64"/></patternFill></fill>'
        '</fills>'
        '<borders count="4">'
        '<!-- 0: None -->'
        '<border><left/><right/><top/><bottom/><diagonal/></border>'
        '<!-- 1: Thin light border (#D8E3F0) -->'
        '<border>'
        '<left style="thin"><color rgb="FFD8E3F0"/></left>'
        '<right style="thin"><color rgb="FFD8E3F0"/></right>'
        '<top style="thin"><color rgb="FFD8E3F0"/></top>'
        '<bottom style="thin"><color rgb="FFD8E3F0"/></bottom>'
        '<diagonal/>'
        '</border>'
        '<!-- 2: Total row border -->'
        '<border>'
        '<left style="thin"><color rgb="FFD8E3F0"/></left>'
        '<right style="thin"><color rgb="FFD8E3F0"/></right>'
        '<top style="thin"><color rgb="FF0A2C1B"/></top>'
        '<bottom style="double"><color rgb="FF0A2C1B"/></bottom>'
        '<diagonal/>'
        '</border>'
        '<!-- 3: Header border -->'
        '<border>'
        '<left style="thin"><color rgb="FF082416"/></left>'
        '<right style="thin"><color rgb="FF082416"/></right>'
        '<top style="thin"><color rgb="FF082416"/></top>'
        '<bottom style="medium"><color rgb="FF082416"/></bottom>'
        '<diagonal/>'
        '</border>'
        '</borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="23">'
        '<!-- 0: normal general -->'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<!-- 1: table header center -->'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="3" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
        '<!-- 2: data cell left-wrap -->'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="top" wrapText="1"/></xf>'
        '<!-- 3: data cell center -->'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
        '<!-- 4: data cell left -->'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>'
        '<!-- 5: Title A1 -->'
        '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>'
        '<!-- 6: Subtitle A2 -->'
        '<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>'
        '<!-- 7: Resumen index center -->'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
        '<!-- 8: Resumen module left -->'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>'
        '<!-- 9: Resumen count center -->'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
        '<!-- 10: Resumen estado red -->'
        '<xf numFmtId="0" fontId="4" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
        '<!-- 11: Resumen estado green -->'
        '<xf numFmtId="0" fontId="5" fillId="4" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
        '<!-- 12: Resumen link left -->'
        '<xf numFmtId="0" fontId="8" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>'
        '<!-- 13: Resumen sin errores left -->'
        '<xf numFmtId="0" fontId="6" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>'
        '<!-- 14: Total label left -->'
        '<xf numFmtId="0" fontId="7" fillId="5" borderId="2" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>'
        '<!-- 15: Total count center -->'
        '<xf numFmtId="0" fontId="7" fillId="5" borderId="2" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
        '<!-- 16: Total estado red -->'
        '<xf numFmtId="0" fontId="4" fillId="3" borderId="2" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
        '<!-- 17: Total estado green -->'
        '<xf numFmtId="0" fontId="5" fillId="4" borderId="2" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
        '<!-- 18: Total empty -->'
        '<xf numFmtId="0" fontId="0" fillId="5" borderId="2" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
        '<!-- 19: table header left -->'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="3" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>'
        '<!-- 20: alternating left-wrap -->'
        '<xf numFmtId="0" fontId="0" fillId="6" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="top" wrapText="1"/></xf>'
        '<!-- 21: alternating center -->'
        '<xf numFmtId="0" fontId="0" fillId="6" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
        '<!-- 22: alternating left -->'
        '<xf numFmtId="0" fontId="0" fillId="6" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>'
        '</cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    )


def _resumen_worksheet_xml(
    summary_modules: list[dict[str, Any]],
    total_inconsistencias: int,
    user_label: str,
    date_label: str,
) -> str:
    row_xml: list[str] = []
    hyperlinks: list[str] = []

    # Row 1: Title
    row_xml.append(
        f'<row r="1" ht="26" customHeight="1">'
        f'{_cell_xml(1, 1, "VALIDADORES DE CALIDAD — RESUMEN DE INCONSISTENCIAS", style=5)}'
        f"</row>"
    )

    # Row 2: Subtitle
    sub_text = f"Generado por: {user_label}  •  Fecha: {date_label}  •  Total inconsistencias: {total_inconsistencias}"
    row_xml.append(
        f'<row r="2" ht="20" customHeight="1">'
        f'{_cell_xml(2, 1, sub_text, style=6)}'
        f"</row>"
    )

    # Row 3: Blank
    row_xml.append('<row r="3" ht="12" customHeight="1"/>')

    # Row 4: Table Header
    headers = ("N°", "Módulo de Calidad", "Inconsistencias", "Estado de Calidad", "Hoja de Detalle")
    header_cells = [
        _cell_xml(4, 1, headers[0], style=1),
        _cell_xml(4, 2, headers[1], style=19),
        _cell_xml(4, 3, headers[2], style=1),
        _cell_xml(4, 4, headers[3], style=1),
        _cell_xml(4, 5, headers[4], style=19),
    ]
    row_xml.append(f'<row r="4" ht="26" customHeight="1">{"".join(header_cells)}</row>')

    # Rows 5 to 5+N-1: Data
    current_row = 5
    for idx, mod in enumerate(summary_modules, start=1):
        count = mod["count"]
        sheet_name = mod.get("sheet_name")

        # Col A: N°
        c_a = _cell_number_xml(current_row, 1, idx, style=7)
        # Col B: Módulo
        c_b = _cell_xml(current_row, 2, mod["label"], style=8)
        # Col C: Inconsistencias
        c_c = _cell_number_xml(current_row, 3, count, style=9)
        # Col D: Estado de Calidad
        if count > 0:
            err_lbl = f"⚠ {count} inconsistencias" if count != 1 else "⚠ 1 inconsistencia"
            c_d = _cell_xml(current_row, 4, err_lbl, style=10)
        else:
            c_d = _cell_xml(current_row, 4, "✓ Cumple (0 errores)", style=11)
        # Col E: Hoja de Detalle
        if count > 0 and sheet_name:
            link_lbl = f"Ir a pestaña '{sheet_name}'"
            c_e = _cell_xml(current_row, 5, link_lbl, style=12)
            cell_ref = f"E{current_row}"
            clean_sname = sheet_name.replace("'", "''")
            clean_loc = escape(f"'{clean_sname}'!A1")
            clean_disp = escape(link_lbl)
            hyperlinks.append(
                f'<hyperlink ref="{cell_ref}" location="{clean_loc}" display="{clean_disp}"/>'
            )
        else:
            c_e = _cell_xml(current_row, 5, "Sin inconsistencias", style=13)

        row_xml.append(
            f'<row r="{current_row}" ht="21" customHeight="1">{c_a}{c_b}{c_c}{c_d}{c_e}</row>'
        )
        current_row += 1

    # Total General Row
    t_a = _cell_xml(current_row, 1, "", style=18)
    t_b = _cell_xml(current_row, 2, "TOTAL GENERAL", style=14)
    t_c = _cell_number_xml(current_row, 3, total_inconsistencias, style=15)
    if total_inconsistencias > 0:
        tot_err_lbl = f"⚠ {total_inconsistencias} errores detectados" if total_inconsistencias != 1 else "⚠ 1 error detectado"
        t_d = _cell_xml(current_row, 4, tot_err_lbl, style=16)
    else:
        t_d = _cell_xml(current_row, 4, "✓ Validación sin errores", style=17)
    t_e = _cell_xml(current_row, 5, "", style=18)

    row_xml.append(
        f'<row r="{current_row}" ht="24" customHeight="1">{t_a}{t_b}{t_c}{t_d}{t_e}</row>'
    )

    hyperlinks_xml = f'<hyperlinks>{"".join(hyperlinks)}</hyperlinks>' if hyperlinks else ""

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="4" topLeftCell="A5" activePane="bottomLeft" state="frozen"/>'
        "</sheetView></sheetViews>"
        '<sheetFormatPr defaultRowHeight="18"/>'
        '<cols>'
        '<col min="1" max="1" width="8" customWidth="1"/>'
        '<col min="2" max="2" width="28" customWidth="1"/>'
        '<col min="3" max="3" width="18" customWidth="1"/>'
        '<col min="4" max="4" width="26" customWidth="1"/>'
        '<col min="5" max="5" width="30" customWidth="1"/>'
        '</cols>'
        f'<sheetData>{"".join(row_xml)}</sheetData>'
        f"{hyperlinks_xml}"
        "</worksheet>"
    )


def _module_worksheet_xml(
    module_label: str,
    module_rows: list[dict[str, str]],
    user_label: str,
    date_label: str,
) -> str:
    row_xml: list[str] = []

    # Row 1: Title
    title_text = f"MÓDULO: {module_label.upper()}"
    row_xml.append(
        f'<row r="1" ht="26" customHeight="1">'
        f'{_cell_xml(1, 1, title_text, style=5)}'
        f"</row>"
    )

    # Row 2: Subtitle
    sub_text = f"Inconsistencias encontradas: {len(module_rows)}  •  Usuario: {user_label}  •  Fecha: {date_label}"
    row_xml.append(
        f'<row r="2" ht="20" customHeight="1">'
        f'{_cell_xml(2, 1, sub_text, style=6)}'
        f"</row>"
    )

    # Row 3: Blank
    row_xml.append('<row r="3" ht="12" customHeight="1"/>')

    # Row 4: Table Header with AutoFilter
    header_cells = [
        _cell_xml(4, 1, HEADERS[0], style=19),
        _cell_xml(4, 2, HEADERS[1], style=19),
        _cell_xml(4, 3, HEADERS[2], style=1),
        _cell_xml(4, 4, HEADERS[3], style=19),
        _cell_xml(4, 5, HEADERS[4], style=1),
        _cell_xml(4, 6, HEADERS[5], style=19),
    ]
    row_xml.append(f'<row r="4" ht="26" customHeight="1">{"".join(header_cells)}</row>')

    # Rows 5 to 5+N-1: Data
    current_row = 5
    if module_rows:
        for idx, row_item in enumerate(module_rows):
            is_alt = (idx % 2 == 1)
            s_left = 22 if is_alt else 4
            s_center = 21 if is_alt else 3
            s_wrap = 20 if is_alt else 2

            cells = [
                _cell_xml(current_row, 1, row_item.get("component", ""), style=s_left),
                _cell_xml(current_row, 2, row_item.get("id", ""), style=s_left),
                _cell_xml(current_row, 3, row_item.get("npn", ""), style=s_center),
                _cell_xml(current_row, 4, row_item.get("layer", ""), style=s_left),
                _cell_xml(current_row, 5, row_item.get("error", ""), style=s_center),
                _cell_xml(current_row, 6, row_item.get("description", ""), style=s_wrap),
            ]
            row_xml.append(f'<row r="{current_row}" ht="20" customHeight="1">{"".join(cells)}</row>')
            current_row += 1
    else:
        # Clean empty row
        cells = [
            _cell_xml(current_row, 1, module_label, style=4),
            _cell_xml(current_row, 2, "-", style=3),
            _cell_xml(current_row, 3, "-", style=3),
            _cell_xml(current_row, 4, "-", style=3),
            _cell_xml(current_row, 5, "-", style=3),
            _cell_xml(current_row, 6, "No hay inconsistencias en este módulo.", style=2),
        ]
        row_xml.append(f'<row r="{current_row}" ht="20" customHeight="1">{"".join(cells)}</row>')
        current_row += 1

    last_row = max(current_row - 1, 4)

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="4" topLeftCell="A5" activePane="bottomLeft" state="frozen"/>'
        "</sheetView></sheetViews>"
        '<sheetFormatPr defaultRowHeight="18"/>'
        '<cols>'
        '<col min="1" max="1" width="20" customWidth="1"/>'
        '<col min="2" max="2" width="36" customWidth="1"/>'
        '<col min="3" max="3" width="34" customWidth="1"/>'
        '<col min="4" max="4" width="26" customWidth="1"/>'
        '<col min="5" max="5" width="16" customWidth="1"/>'
        '<col min="6" max="6" width="75" customWidth="1"/>'
        '</cols>'
        f'<sheetData>{"".join(row_xml)}</sheetData>'
        f'<autoFilter ref="A4:F{last_row}"/>'
        "</worksheet>"
    )


def build_validation_errors_excel(report: dict[str, Any]) -> bytes:
    user_label = _clean_text(report.get("username") or "Usuario")
    date_label = _format_date(report.get("generated_at"))

    selected_comp = report.get("selected_component")
    all_rows = _error_rows(report)

    sheets: list[dict[str, Any]] = []
    used_names: set[str] = set()

    if selected_comp:
        # Single module mode
        comp_label = _clean_text(report.get("selected_component_label") or selected_comp.replace("_", " ").title())
        sheet_name = _safe_sheet_name(comp_label, used_names)
        xml_content = _module_worksheet_xml(
            module_label=comp_label,
            module_rows=all_rows,
            user_label=user_label,
            date_label=date_label,
        )
        sheets.append({"name": sheet_name, "xml": xml_content})
    else:
        # All modules mode: Resumen + module sheets with errors
        # Group error rows by normalized module slug
        rows_by_slug: dict[str, list[dict[str, str]]] = {}
        for r in all_rows:
            slug = _normalize_module_slug(r.get("component"))
            rows_by_slug.setdefault(slug, []).append(r)

        # Build summary modules list
        summary_modules: list[dict[str, Any]] = []
        handled_slugs: set[str] = set()

        for std in STANDARD_MODULES:
            slug = std["slug"]
            label = std["label"]
            handled_slugs.add(slug)
            m_rows = rows_by_slug.get(slug, [])
            count = len(m_rows)
            sheet_name = label if count > 0 else None
            summary_modules.append({
                "slug": slug,
                "label": label,
                "count": count,
                "sheet_name": sheet_name,
                "rows": m_rows,
            })

        # Extra slugs if any
        for slug, m_rows in rows_by_slug.items():
            if slug not in handled_slugs:
                label = slug.replace("_", " ").title()
                summary_modules.append({
                    "slug": slug,
                    "label": label,
                    "count": len(m_rows),
                    "sheet_name": label,
                    "rows": m_rows,
                })

        total_inconsistencias = len(all_rows)

        # Sheet 1: Resumen
        resumen_sheet_name = _safe_sheet_name("Resumen", used_names)
        resumen_xml = _resumen_worksheet_xml(
            summary_modules=summary_modules,
            total_inconsistencias=total_inconsistencias,
            user_label=user_label,
            date_label=date_label,
        )
        sheets.append({"name": resumen_sheet_name, "xml": resumen_xml})

        # Detail sheets for modules with count > 0
        for mod in summary_modules:
            if mod["count"] > 0:
                sheet_name = _safe_sheet_name(mod["label"], used_names)
                mod["sheet_name"] = sheet_name
                mod_xml = _module_worksheet_xml(
                    module_label=mod["label"],
                    module_rows=mod["rows"],
                    user_label=user_label,
                    date_label=date_label,
                )
                sheets.append({"name": sheet_name, "xml": mod_xml})

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
                sheet["xml"],
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
    component_slug = _filename_component(report)
    if component_slug:
        return f"Usuario_errores_validacion_{component_slug}_{generated_at:%Y%m%d_%H%M}.xlsx"
    return f"Usuario_errores_validacion_{generated_at:%Y%m%d_%H%M}.xlsx"


def _filename_component(report: dict[str, Any]) -> str:
    component = str(report.get("selected_component") or "").strip().lower()
    return re.sub(r"[^a-z0-9_-]+", "_", component).strip("_")


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

