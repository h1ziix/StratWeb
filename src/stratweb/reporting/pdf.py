"""Deterministic, Cyrillic-capable PDF renderer for evidence reports."""

from __future__ import annotations

from collections.abc import Callable
from html import escape
from io import BytesIO
from pathlib import Path
from threading import Lock
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    CondPageBreak,
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from stratweb.findings.models import FindingText
from stratweb.reporting.models import ScoutingReportExport
from stratweb.reporting.presentation import (
    check_label,
    check_message,
    finding_observation,
    finding_title,
    limitation_label,
    status_label,
    warning_label,
)

_FONT_REGULAR = "StratWebSans"
_FONT_BOLD = "StratWebSansBold"
_FONT_LOCK = Lock()
_FONTS_READY = False

_REGULAR_CANDIDATES = (
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
)
_BOLD_CANDIDATES = (
    Path("C:/Windows/Fonts/arialbd.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
)


class PdfFontUnavailableError(RuntimeError):
    """Raised when no Unicode font required for Russian report text is installed."""


class ScoutingReportPdfRenderer:
    def render(self, report: ScoutingReportExport) -> bytes:
        _ensure_fonts()
        buffer = BytesIO()
        styles = _styles()
        document = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=17 * mm,
            rightMargin=17 * mm,
            topMargin=20 * mm,
            bottomMargin=18 * mm,
            title=f"StratWeb - {report.display_name}",
            author="StratWeb",
            subject="Evidence-based offline CS2 scouting report",
            creator=f"StratWeb {report.export_rule_version}",
            invariant=1,
            pageCompression=1,
            lang="ru-RU",
        )
        story = self._story(report, styles)
        page = _page_decorator(report, styles)
        document.build(story, onFirstPage=page, onLaterPages=page)
        return buffer.getvalue()

    def _story(
        self,
        report: ScoutingReportExport,
        styles: dict[str, ParagraphStyle],
    ) -> list[Any]:
        story: list[Any] = [
            Paragraph("STRATWEB / ДОКАЗАТЕЛЬНЫЙ ОТЧЁТ", styles["eyebrow"]),
            Paragraph(_safe(report.display_name), styles["title"]),
            Paragraph(
                "Офлайн-анализ завершённых матчей CS2. Статистика рассчитана "
                "детерминированным кодом; неизвестные значения не заменены предположениями.",
                styles["lead"],
            ),
            Spacer(1, 5 * mm),
            _summary_table(report, styles),
            Spacer(1, 5 * mm),
            Paragraph("Ограничения выборки", styles["h2"]),
        ]
        limitations = report.sample_limitations or ("Явных ограничений не зарегистрировано.",)
        story.extend(_bullet(warning_label(item), styles) for item in limitations)
        if report.warnings:
            story.extend((Spacer(1, 2 * mm), Paragraph("Предупреждения", styles["h2"])))
            story.extend(_bullet(warning_label(item), styles) for item in report.warnings)

        story.extend(
            (
                Spacer(1, 4 * mm),
                Paragraph("Качество и воспроизводимость", styles["h2"]),
                _versions_table(report, styles),
                Spacer(1, 3 * mm),
                _checks_table(report, styles),
                PageBreak(),
                Paragraph("Корпус демок", styles["h1"]),
                Paragraph(
                    "Исходные имена приведены только как метаданные. SHA-256 является "
                    "идентификатором содержимого демки.",
                    styles["body"],
                ),
                Spacer(1, 3 * mm),
                _corpus_table(report, styles),
                PageBreak(),
                Paragraph("Наблюдения и рекомендации", styles["h1"]),
            )
        )
        recommendation_by_finding = {
            item.source_finding_id: item for item in report.recommendations
        }
        for index, finding in enumerate(report.findings, start=1):
            story.extend(
                (
                    CondPageBreak(55 * mm),
                    Paragraph(f"{index}. {_safe(finding_title(finding))}", styles["h2"]),
                    Paragraph(
                        _safe(
                            " / ".join(
                                (
                                    finding.scope.map_name,
                                    finding.scope.side.value,
                                    finding.scope.buy_type.value
                                    if finding.scope.buy_type is not None
                                    else "закупка неизвестна",
                                    finding.pattern_type.value,
                                )
                            )
                        ),
                        styles["meta"],
                    ),
                    _finding_stats(finding, styles),
                    Paragraph("Наблюдение", styles["label"]),
                    Paragraph(_safe(finding_observation(finding)), styles["body"]),
                )
            )
            recommendation = recommendation_by_finding.get(finding.finding_id)
            if recommendation is not None:
                story.extend(
                    (
                        Paragraph("Тактическая интерпретация", styles["label"]),
                        Paragraph(
                            _finding_text(recommendation.tactical_interpretation),
                            styles["body"],
                        ),
                        Paragraph("Рекомендуемый ответ", styles["label"]),
                        Paragraph(_finding_text(recommendation.recommendation), styles["body"]),
                        Paragraph("Чего избегать", styles["label"]),
                        Paragraph(_finding_text(recommendation.avoid), styles["body"]),
                    )
                )
            else:
                story.append(
                    Paragraph(
                        "Тактическая рекомендация не опубликована: наблюдение не прошло "
                        "все правила готовности или не имеет поддерживаемого правила.",
                        styles["warning"],
                    )
                )
            story.append(Paragraph("Ограничения", styles["label"]))
            story.extend(_bullet(limitation_label(item), styles) for item in finding.limitations)
            story.extend(
                (
                    Paragraph(
                        f"Приложение доказательств: {len(finding.evidence_references)} записей",
                        styles["label"],
                    ),
                    _evidence_table(finding.evidence_references, styles),
                    Spacer(1, 3 * mm),
                    HRFlowable(width="100%", color=colors.HexColor("#CED7E0"), thickness=0.5),
                    Spacer(1, 3 * mm),
                )
            )
        return story


def _ensure_fonts() -> None:
    global _FONTS_READY
    if _FONTS_READY:
        return
    with _FONT_LOCK:
        if _FONTS_READY:
            return
        regular = next((item for item in _REGULAR_CANDIDATES if item.is_file()), None)
        bold = next((item for item in _BOLD_CANDIDATES if item.is_file()), None)
        if regular is None or bold is None:
            raise PdfFontUnavailableError(
                "Unicode PDF font is unavailable. Install Arial or fonts-dejavu-core."
            )
        pdfmetrics.registerFont(TTFont(_FONT_REGULAR, str(regular)))
        pdfmetrics.registerFont(TTFont(_FONT_BOLD, str(bold)))
        pdfmetrics.registerFontFamily(
            "StratWebSansFamily",
            normal=_FONT_REGULAR,
            bold=_FONT_BOLD,
        )
        _FONTS_READY = True


def _styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title",
            parent=sample["Title"],
            fontName=_FONT_BOLD,
            fontSize=25,
            leading=29,
            textColor=colors.HexColor("#101923"),
            alignment=TA_LEFT,
            spaceAfter=7,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=sample["Heading1"],
            fontName=_FONT_BOLD,
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#101923"),
            spaceAfter=9,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=sample["Heading2"],
            fontName=_FONT_BOLD,
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#152334"),
            spaceBefore=8,
            spaceAfter=5,
        ),
        "eyebrow": ParagraphStyle(
            "Eyebrow",
            parent=sample["Normal"],
            fontName=_FONT_BOLD,
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#087E86"),
            spaceAfter=4,
        ),
        "lead": ParagraphStyle(
            "Lead",
            parent=sample["Normal"],
            fontName=_FONT_REGULAR,
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#435064"),
        ),
        "body": ParagraphStyle(
            "Body",
            parent=sample["BodyText"],
            fontName=_FONT_REGULAR,
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#202B38"),
            spaceAfter=5,
            splitLongWords=True,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=sample["BodyText"],
            fontName=_FONT_REGULAR,
            fontSize=6.5,
            leading=8.5,
            textColor=colors.HexColor("#344152"),
            splitLongWords=True,
        ),
        "meta": ParagraphStyle(
            "Meta",
            parent=sample["BodyText"],
            fontName=_FONT_REGULAR,
            fontSize=7.5,
            leading=10,
            textColor=colors.HexColor("#667386"),
            spaceAfter=5,
        ),
        "label": ParagraphStyle(
            "Label",
            parent=sample["BodyText"],
            fontName=_FONT_BOLD,
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#087E86"),
            spaceBefore=4,
            spaceAfter=2,
        ),
        "warning": ParagraphStyle(
            "Warning",
            parent=sample["BodyText"],
            fontName=_FONT_REGULAR,
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#7C4A00"),
            backColor=colors.HexColor("#FFF3D8"),
            borderPadding=6,
            spaceAfter=5,
        ),
        "footer": ParagraphStyle(
            "Footer",
            parent=sample["Normal"],
            fontName=_FONT_REGULAR,
            fontSize=6.5,
            leading=8,
            textColor=colors.HexColor("#677587"),
            alignment=TA_CENTER,
        ),
    }


def _page_decorator(
    report: ScoutingReportExport,
    styles: dict[str, ParagraphStyle],
) -> Callable[[Canvas, SimpleDocTemplate], None]:
    def draw(canvas: Canvas, document: SimpleDocTemplate) -> None:
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D5DEE7"))
        canvas.line(17 * mm, 14 * mm, A4[0] - 17 * mm, 14 * mm)
        footer = Paragraph(
            _safe(
                f"StratWeb · стр. {canvas.getPageNumber()} · export "
                f"{report.export_fingerprint[:12]}"
            ),
            styles["footer"],
        )
        footer.wrapOn(canvas, A4[0] - 34 * mm, 7 * mm)
        footer.drawOn(canvas, 17 * mm, 6 * mm)
        canvas.restoreState()

    return draw


def _summary_table(report: ScoutingReportExport, styles: dict[str, ParagraphStyle]) -> Table:
    analysis_date = report.analysis_created_at.isoformat() if report.analysis_created_at else "—"
    data = [
        ["Статус", status_label(report.acceptance_status), "Дата анализа", analysis_date],
        [
            "Корпус",
            f"{report.scope.included_matches}/{report.scope.required_matches}",
            "Наблюдения",
            str(report.scope.source_findings),
        ],
        [
            "Рекомендации",
            str(report.scope.recommendations),
            "Доказательства",
            str(report.scope.evidence_references),
        ],
        [
            "Карты",
            ", ".join(report.scope.maps) or "—",
            "Стороны",
            ", ".join(report.scope.sides) or "—",
        ],
    ]
    table = Table(
        [[Paragraph(_safe(str(cell)), styles["body"]) for cell in row] for row in data],
        colWidths=(27 * mm, 50 * mm, 30 * mm, 55 * mm),
    )
    table.setStyle(_base_table_style(header=False))
    return table


def _versions_table(report: ScoutingReportExport, styles: dict[str, ParagraphStyle]) -> Table:
    rows = [["Компонент", "Схема", "Правило"]]
    rows.extend(
        (
            ["Экспорт", report.export_schema_version, report.export_rule_version],
            [
                "Анализ",
                report.versions.analysis_schema_version,
                report.versions.analysis_rule_version,
            ],
            [
                "Паттерны",
                report.versions.source_pattern_schema_version,
                report.versions.source_pattern_rule_version,
            ],
            [
                "Готовность",
                report.versions.readiness_schema_version,
                report.versions.readiness_rule_version,
            ],
            [
                "Контрстратегия",
                report.versions.strategy_schema_version,
                report.versions.strategy_rule_version,
            ],
            [
                "Проверка",
                report.versions.validation_schema_version,
                report.versions.validation_rule_version,
            ],
            [
                "Профиль соперника",
                report.versions.opponent_schema_version,
                (
                    f"{report.versions.opponent_identity_rule_version}; "
                    f"{report.versions.opponent_overlap_rule_version}"
                ),
            ],
        )
    )
    return _paragraph_table(rows, styles, (39 * mm, 35 * mm, 88 * mm), repeat_rows=1)


def _checks_table(report: ScoutingReportExport, styles: dict[str, ParagraphStyle]) -> Table:
    rows = [["Проверка", "Статус", "Результат"]]
    rows.extend(
        [check_label(item.code.value), status_label(item.status.value), check_message(item)]
        for item in report.validation.checks
    )
    return _paragraph_table(rows, styles, (45 * mm, 25 * mm, 92 * mm), repeat_rows=1)


def _corpus_table(report: ScoutingReportExport, styles: dict[str, ParagraphStyle]) -> Table:
    rows = [["Карта / матч", "Демка / SHA-256", "Команда / раунды", "Статус"]]
    for item in report.corpus:
        rows.append(
            [
                f"{item.map_name}\n{item.match_id}",
                f"{item.original_file_name or '—'}\n{item.demo_sha256 or '—'}",
                (
                    f"{item.opponent_team_name or '—'}\n"
                    f"{item.round_count if item.round_count is not None else '—'}"
                ),
                item.input_status
                + (f"\n{item.exclusion_reason}" if item.exclusion_reason else ""),
            ]
        )
    return _paragraph_table(rows, styles, (41 * mm, 61 * mm, 35 * mm, 25 * mm), repeat_rows=1)


def _finding_stats(finding: Any, styles: dict[str, ParagraphStyle]) -> Table:
    confidence = finding.confidence
    rows = [
        ["Числитель", "Знаменатель", "Частота", "Выборка", "Confidence"],
        [
            str(finding.numerator),
            str(finding.denominator),
            f"{finding.frequency:.1%}",
            str(finding.sample_size),
            (
                f"{confidence.score:.1%} "
                f"[{confidence.lower_bound:.1%}; {confidence.upper_bound:.1%}]"
            ),
        ],
    ]
    return _paragraph_table(
        rows,
        styles,
        (25 * mm, 27 * mm, 25 * mm, 24 * mm, 61 * mm),
        repeat_rows=1,
    )


def _evidence_table(evidence: tuple[Any, ...], styles: dict[str, ParagraphStyle]) -> Table:
    rows = [["Матч / раунд / тик", "События", "Описание / SHA-256"]]
    for item in evidence:
        tick = str(item.tick) if item.tick is not None else "неизвестно"
        event_references = ", ".join(f"event {value}" for value in item.event_ids)
        reference_summary = "; ".join(
            (
                f"feature IDs: {len(item.feature_ids)}",
                f"spatial snapshot IDs: {len(item.snapshot_ids)}",
                f"economy snapshot IDs: {len(item.economy_snapshot_ids)}",
            )
        )
        rows.append(
            [
                f"{item.match_id}\nR{item.round_number} / tick {tick}\n{item.evidence_id}",
                f"{event_references or 'event IDs: 0'}; {reference_summary}",
                f"{item.description}\n{item.demo_sha256}",
            ]
        )
    return _paragraph_table(rows, styles, (55 * mm, 47 * mm, 60 * mm), repeat_rows=1, small=True)


def _paragraph_table(
    rows: list[list[str]],
    styles: dict[str, ParagraphStyle],
    widths: tuple[float, ...],
    *,
    repeat_rows: int,
    small: bool = False,
) -> Table:
    body_style = styles["small"] if small else styles["body"]
    converted = [
        [
            Paragraph(
                _safe(cell).replace("\n", "<br/>"),
                styles["label"] if row == 0 else body_style,
            )
            for cell in values
        ]
        for row, values in enumerate(rows)
    ]
    table = Table(converted, colWidths=widths, repeatRows=repeat_rows, hAlign="LEFT")
    table.setStyle(_base_table_style(header=True))
    return table


def _base_table_style(*, header: bool) -> TableStyle:
    commands: list[tuple[Any, ...]] = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5DF")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        (
            "ROWBACKGROUNDS",
            (0, 1 if header else 0),
            (-1, -1),
            [colors.white, colors.HexColor("#F5F8FA")],
        ),
    ]
    if header:
        commands.extend(
            (
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F4F5")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#087E86")),
            )
        )
    return TableStyle(commands)


def _finding_text(value: FindingText) -> str:
    if value.text is not None:
        return _safe(value.text)
    return _safe(f"Недоступно: {value.reason or 'причина не указана'}")


def _bullet(value: str, styles: dict[str, ParagraphStyle]) -> Paragraph:
    return Paragraph(f"• {_safe(value)}", styles["body"])


def _safe(value: str) -> str:
    return escape(value, quote=False).replace("\n", "<br/>")


__all__ = ["PdfFontUnavailableError", "ScoutingReportPdfRenderer"]
