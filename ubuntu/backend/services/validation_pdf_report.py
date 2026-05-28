from __future__ import annotations

from datetime import datetime
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Any


def build_validation_pdf(report: dict[str, Any], watermark_path: Path) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:
        raise RuntimeError(
            "ReportLab no esta instalado. Instala las dependencias del backend con "
            "`pip install -r backend/requirements.txt`."
        ) from exc

    buffer = BytesIO()
    page_width, page_height = A4
    margin_x = 57

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=margin_x,
        rightMargin=margin_x,
        topMargin=72,
        bottomMargin=58,
        title="Reporte de validacion de reglas de calidad",
    )

    title_color = colors.HexColor("#003B5C")
    rule_color = colors.HexColor("#00556B")
    green = colors.HexColor("#008000")
    red = colors.HexColor("#B00020")
    amber = colors.HexColor("#8A6514")
    black = colors.HexColor("#000000")

    title_style = ParagraphStyle(
        "ValidationTitle",
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=27,
        leftIndent=18,
        textColor=title_color,
        spaceAfter=28,
    )
    body_style = ParagraphStyle(
        "ValidationBody",
        fontName="Helvetica",
        fontSize=9.2,
        leading=12,
        alignment=TA_LEFT,
        textColor=black,
    )
    rule_title_style = ParagraphStyle(
        "ValidationRuleTitle",
        parent=body_style,
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=13,
        textColor=rule_color,
        spaceAfter=10,
    )
    description_style = ParagraphStyle(
        "ValidationDescription",
        parent=body_style,
        fontSize=9,
        leading=11.5,
        spaceAfter=13,
    )
    success_style = ParagraphStyle(
        "ValidationSuccess",
        parent=body_style,
        fontName="Helvetica-Bold",
        textColor=green,
    )
    failed_style = ParagraphStyle(
        "ValidationFailed",
        parent=success_style,
        textColor=red,
    )
    warning_style = ParagraphStyle(
        "ValidationWarning",
        parent=success_style,
        textColor=amber,
    )
    section_style = ParagraphStyle(
        "ValidationSection",
        parent=title_style,
        fontSize=16,
        leading=20,
        leftIndent=0,
        spaceBefore=8,
        spaceAfter=12,
    )

    def draw_background(canvas, _doc):
        canvas.saveState()
        if watermark_path and watermark_path.is_file():
            canvas.drawImage(
                str(watermark_path),
                0,
                0,
                width=page_width,
                height=page_height,
                preserveAspectRatio=False,
                mask="auto",
            )
        canvas.restoreState()

    story: list[Any] = [
        Paragraph("Reporte de validación de reglas de calidad", title_style),
        Paragraph(_intro_text(report), body_style),
        Spacer(1, 14),
    ]

    rules = _rules_for_report(report)
    if rules:
        for rule in rules:
            passed = bool(rule.get("passed"))
            issue_count = _coerce_int(rule.get("issue_count"), default=0)
            border_color = green if passed else red
            status_style = success_style if passed else failed_style
            status_text = (
                "Cumple validación de calidad"
                if passed
                else f"No cumple validación de calidad ({issue_count} errores)"
            )

            description = _safe_text(
                rule.get("description")
                or rule.get("descripcion")
                or "Sin descripción disponible."
            )
            cell_flowables = [
                Paragraph(f"Regla: {_safe_text(rule.get('rule') or 'Sin código')}", rule_title_style),
                Paragraph(f"<b>Descripción:</b> {description}", description_style),
                Paragraph(status_text, status_style),
            ]

            story.append(
                Table(
                    [[cell_flowables]],
                    colWidths=[doc.width],
                    style=TableStyle(
                        [
                            ("BOX", (0, 0), (-1, -1), 1, border_color),
                            ("LEFTPADDING", (0, 0), (-1, -1), 10),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                            ("TOPPADDING", (0, 0), (-1, -1), 9),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                        ]
                    ),
                )
            )
            story.append(Spacer(1, 10))
    else:
        story.append(
            Paragraph("No hay información de reglas disponible para este resultado.", warning_style)
        )

    schema_errors = _as_list((report.get("validation") or {}).get("schema_errors"))
    if schema_errors:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Errores estructurales del archivo XTF", section_style))
        for item in schema_errors[:200]:
            message = _safe_text(item.get("message") or "Sin detalle adicional")
            object_id = _safe_text(
                item.get("display_id")
                or item.get("object_id")
                or item.get("tid")
                or "Sin identificar"
            )
            object_class = _safe_text(item.get("object_class") or "Clase no declarada")
            cell_flowables = [
                Paragraph(f"<b>Predio / TID:</b> {object_id}", description_style),
                Paragraph(f"<b>Clase:</b> {object_class}", description_style),
                Paragraph(f"<b>Detalle:</b> {message}", description_style),
            ]
            story.append(
                Table(
                    [[cell_flowables]],
                    colWidths=[doc.width],
                    style=TableStyle(
                        [
                            ("BOX", (0, 0), (-1, -1), 1, red),
                            ("LEFTPADDING", (0, 0), (-1, -1), 10),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                            ("TOPPADDING", (0, 0), (-1, -1), 8),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                        ]
                    ),
                )
            )
            story.append(Spacer(1, 8))

    doc.build(story, onFirstPage=draw_background, onLaterPages=draw_background)
    return buffer.getvalue()


def validation_pdf_filename(report: dict[str, Any]) -> str:
    raw_date = str(report.get("generated_at") or "").strip()
    generated_at: datetime | None = None
    if raw_date:
        try:
            generated_at = datetime.fromisoformat(raw_date)
        except ValueError:
            generated_at = None
    if generated_at is None:
        generated_at = datetime.now()
    return f"Usuario_reporte_validacion_{generated_at:%Y%m%d_%H%M}.pdf"


def _intro_text(report: dict[str, Any]) -> str:
    validation = report.get("validation") or {}
    status = str(validation.get("status") or "").lower()

    if status == "success":
        prefix = "El archivo XTF suministrado es válido."
    elif status == "invalid":
        prefix = "El archivo XTF suministrado presenta hallazgos de validación."
    elif status == "skipped":
        prefix = "No se pudo ejecutar completamente la validación automática."
    else:
        prefix = "No se pudo determinar correctamente el resultado de la validación."

    return (
        f"{prefix} A continuación, se presentan los resultados de las reglas de calidad "
        "definidas para dicho modelo."
    )


def _rules_for_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    validation = report.get("validation") or {}
    quality = validation.get("quality") or {}
    catalog = quality.get("rule_catalog") or {}
    rules = _as_list(quality.get("rules"))

    normalized: list[dict[str, Any]] = []
    for item in rules:
        if not isinstance(item, dict):
            continue
        rule_id = str(item.get("rule") or item.get("rule_id") or "").strip()
        catalog_item = catalog.get(rule_id) if isinstance(catalog, dict) else {}
        if not isinstance(catalog_item, dict):
            catalog_item = {}
        issue_count = _coerce_int(item.get("issue_count"), default=0)
        passed = item.get("passed")
        if passed is None:
            passed = issue_count == 0
        normalized.append(
            {
                "rule": rule_id or "Sin código",
                "description": item.get("description") or catalog_item.get("description"),
                "issue_count": issue_count,
                "passed": bool(passed),
            }
        )

    if normalized:
        return sorted(normalized, key=lambda item: _rule_sort_key(str(item.get("rule") or "")))

    grouped: dict[str, int] = {}
    for item in _as_list(validation.get("rule_errors")):
        if not isinstance(item, dict):
            continue
        rule_id = str(item.get("rule") or item.get("rule_id") or "No disponible").strip()
        grouped[rule_id] = grouped.get(rule_id, 0) + 1

    return [
        {
            "rule": rule_id,
            "description": (catalog.get(rule_id) or {}).get("description") if isinstance(catalog, dict) else None,
            "issue_count": count,
            "passed": count == 0,
        }
        for rule_id, count in sorted(grouped.items(), key=lambda item: _rule_sort_key(item[0]))
    ]


def _safe_text(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return escape(text).replace("\n", "<br/>")


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _rule_sort_key(rule_id: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in str(rule_id).split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(999999)
    return tuple(parts)
