from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.graphics.widgets.markers import makeMarker
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

MAX_TABLE_ROWS = 1000

CHART_WIDTH = 174 * mm
CHART_HEIGHT = 68 * mm
MARKER_LIMIT = 60  # show point markers only when a line has this many points or fewer

GLUCOSE_COLOR = colors.HexColor("#198754")
SYSTOLIC_COLOR = colors.HexColor("#dc3545")
DIASTOLIC_COLOR = colors.HexColor("#0d6efd")

TYPE_LABELS = {
    "fasting": "Fasting",
    "before_meal": "Before meal",
    "after_meal": "After meal",
}

DISCLAIMER = (
    "This report only lists values recorded by the user. It is not medical advice. "
    "It does not diagnose any condition, prescribe medicine or recommend treatment. "
    "Please discuss your health with a qualified healthcare professional."
)


@dataclass
class GlucoseRow:
    recorded_at: datetime  # timezone-aware, UTC
    value: float
    reading_type: str
    notes: str | None


@dataclass
class PressureRow:
    recorded_at: datetime  # timezone-aware, UTC
    systolic: int
    diastolic: int
    pulse: int | None
    notes: str | None


def _number(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _offset_label(offset_minutes: int) -> str:
    sign = "+" if offset_minutes >= 0 else "-"
    hours, minutes = divmod(abs(offset_minutes), 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def _local(value: datetime, offset_minutes: int) -> datetime:
    return value.astimezone(timezone.utc) + timedelta(minutes=offset_minutes)


def _stamp(value: datetime, offset_minutes: int) -> str:
    return _local(value, offset_minutes).strftime("%Y-%m-%d %H:%M")


def _text(value: str | None) -> str:
    """Escape user text so it is shown literally and can never act as markup."""
    return escape(value or "")


def _glucose_stats(rows: list[GlucoseRow]) -> list[list[str]]:
    values = [row.value for row in rows]
    return [
        ["Readings", str(len(values))],
        ["Average", _number(sum(values) / len(values))],
        ["Lowest", _number(min(values))],
        ["Highest", _number(max(values))],
    ]


def _pressure_stats(rows: list[PressureRow]) -> list[list[str]]:
    systolic = [row.systolic for row in rows]
    diastolic = [row.diastolic for row in rows]
    pulses = [row.pulse for row in rows if row.pulse is not None]
    average_pulse = _number(sum(pulses) / len(pulses)) if pulses else "-"
    return [
        ["Readings", str(len(rows))],
        [
            "Average (systolic/diastolic)",
            f"{_number(sum(systolic) / len(rows))}/{_number(sum(diastolic) / len(rows))}",
        ],
        ["Systolic range", f"{min(systolic)}-{max(systolic)}"],
        ["Diastolic range", f"{min(diastolic)}-{max(diastolic)}"],
        ["Average pulse", average_pulse],
    ]


def _stats_table(rows: list[list[str]]) -> Table:
    table = Table(rows, colWidths=[70 * mm, 50 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return table


def _readings_table(header: list[str], rows: list[list], widths: list[float]) -> Table:
    table = Table([header] + rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def _line_chart(
    title: str,
    series: list[tuple[str, colors.Color, list[tuple[datetime, float]]]],
    start: datetime,
    end: datetime,
    offset_minutes: int,
) -> Drawing:
    """A line chart of readings over the whole report period.

    `series` is a list of (name, colour, [(UTC time, value), ...]). Every series
    must have at least one point. The horizontal axis always covers the full
    period, in the same time zone as the rest of the report.
    """
    base = _local(start, offset_minutes)
    span_days = max((end - start).total_seconds() / 86400, 1 / 24)

    data = []
    for _name, _color, points in series:
        data.append(
            [
                ((_local(when, offset_minutes) - base).total_seconds() / 86400, float(value))
                for when, value in points
            ]
        )

    all_y = [y for line in data for _x, y in line]
    low, high = min(all_y), max(all_y)
    pad = max((high - low) * 0.1, 1.0)
    y_min = max(0.0, low - pad)
    y_max = high + pad

    drawing = Drawing(CHART_WIDTH, CHART_HEIGHT)
    drawing.hAlign = "LEFT"

    plot = LinePlot()
    plot.x = 40
    plot.y = 26
    plot.width = CHART_WIDTH - 55
    plot.height = CHART_HEIGHT - 52
    plot.data = data

    for index, (_name, color, _points) in enumerate(series):
        line = plot.lines[index]
        line.strokeColor = color
        line.strokeWidth = 1.4
        if len(data[index]) <= MARKER_LIMIT:
            marker = makeMarker("FilledCircle")
            marker.size = 4
            marker.fillColor = color
            marker.strokeColor = color
            line.symbol = marker

    label_format = "%d %b %H:%M" if span_days <= 2 else "%d %b"
    x_axis = plot.xValueAxis
    x_axis.valueMin = 0
    x_axis.valueMax = span_days
    x_axis.valueSteps = [span_days * i / 5 for i in range(6)]
    x_axis.labelTextFormat = lambda v: (base + timedelta(days=v)).strftime(label_format)
    x_axis.labels.fontName = "Helvetica"
    x_axis.labels.fontSize = 7

    y_axis = plot.yValueAxis
    y_axis.valueMin = y_min
    y_axis.valueMax = y_max
    y_axis.labelTextFormat = "%g"
    y_axis.labels.fontName = "Helvetica"
    y_axis.labels.fontSize = 7
    y_axis.visibleGrid = True
    y_axis.gridStrokeColor = colors.lightgrey
    y_axis.gridStrokeWidth = 0.4

    drawing.add(plot)
    drawing.add(
        String(
            40,
            CHART_HEIGHT - 12,
            title,
            fontName="Helvetica-Bold",
            fontSize=9,
            fillColor=colors.black,
        )
    )

    if len(series) > 1:
        legend_x = CHART_WIDTH - 15 - 65 * len(series)
        for index, (name, color, _points) in enumerate(series):
            x = legend_x + index * 65
            drawing.add(
                Rect(x, CHART_HEIGHT - 13, 8, 8, fillColor=color, strokeColor=color)
            )
            drawing.add(
                String(
                    x + 12,
                    CHART_HEIGHT - 12,
                    name,
                    fontName="Helvetica",
                    fontSize=8,
                    fillColor=colors.black,
                )
            )
    return drawing


def _footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.grey)
    canvas.drawString(18 * mm, 10 * mm, "MediTrack AI report. Not medical advice.")
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build_report_pdf(
    *,
    full_name: str,
    start: datetime,
    end: datetime,
    glucose: list[GlucoseRow],
    pressure: list[PressureRow],
    offset_minutes: int = 0,
    generated_at: datetime | None = None,
    compress: bool = True,
) -> bytes:
    """Build the report and return the PDF file as bytes."""
    generated_at = generated_at or datetime.now(timezone.utc)

    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    heading_style = styles["Heading2"]
    body_style = styles["BodyText"]
    small_style = ParagraphStyle("small", parent=body_style, fontSize=8, leading=10)
    cell_style = ParagraphStyle("cell", parent=body_style, fontSize=8.5, leading=10.5)

    zone = _offset_label(offset_minutes)
    first_day = _local(start, offset_minutes).strftime("%Y-%m-%d")
    last_day = _local(end - timedelta(seconds=1), offset_minutes).strftime("%Y-%m-%d")

    story = [
        Paragraph("MediTrack AI Health Report", title_style),
        Paragraph(f"Prepared for: {_text(full_name)}", body_style),
        Paragraph(f"Period: {first_day} to {last_day}", body_style),
        Paragraph(
            f"Generated: {_stamp(generated_at, offset_minutes)}. "
            f"All times are shown in {zone}.",
            body_style,
        ),
        Spacer(1, 6 * mm),
    ]

    # ---- Blood glucose --------------------------------------------------
    story.append(Paragraph("Blood glucose", heading_style))
    if not glucose:
        story.append(Paragraph("No glucose readings in this period.", body_style))
    else:
        story.append(_stats_table(_glucose_stats(glucose)))
        story.append(Spacer(1, 4 * mm))
        story.append(
            _line_chart(
                "Blood glucose over time",
                [("Glucose", GLUCOSE_COLOR, [(r.recorded_at, r.value) for r in glucose])],
                start,
                end,
                offset_minutes,
            )
        )
        story.append(Spacer(1, 4 * mm))
        shown = glucose[-MAX_TABLE_ROWS:]
        if len(shown) < len(glucose):
            story.append(
                Paragraph(
                    f"The table lists the most recent {len(shown)} of {len(glucose)} "
                    "readings. The statistics and chart include all of them.",
                    small_style,
                )
            )
        rows = [
            [
                _stamp(r.recorded_at, offset_minutes),
                _number(r.value),
                TYPE_LABELS.get(r.reading_type, r.reading_type),
                Paragraph(_text(r.notes), cell_style),
            ]
            for r in shown
        ]
        story.append(
            _readings_table(
                ["Date and time", "Glucose value", "Type", "Notes"],
                rows,
                [38 * mm, 28 * mm, 28 * mm, 80 * mm],
            )
        )
    story.append(Spacer(1, 6 * mm))

    # ---- Blood pressure -------------------------------------------------
    story.append(Paragraph("Blood pressure", heading_style))
    if not pressure:
        story.append(Paragraph("No blood pressure readings in this period.", body_style))
    else:
        story.append(_stats_table(_pressure_stats(pressure)))
        story.append(Spacer(1, 4 * mm))
        story.append(
            _line_chart(
                "Blood pressure over time",
                [
                    (
                        "Systolic",
                        SYSTOLIC_COLOR,
                        [(r.recorded_at, r.systolic) for r in pressure],
                    ),
                    (
                        "Diastolic",
                        DIASTOLIC_COLOR,
                        [(r.recorded_at, r.diastolic) for r in pressure],
                    ),
                ],
                start,
                end,
                offset_minutes,
            )
        )
        story.append(Spacer(1, 4 * mm))
        shown_bp = pressure[-MAX_TABLE_ROWS:]
        if len(shown_bp) < len(pressure):
            story.append(
                Paragraph(
                    f"The table lists the most recent {len(shown_bp)} of {len(pressure)} "
                    "readings. The statistics and chart include all of them.",
                    small_style,
                )
            )
        rows_bp = [
            [
                _stamp(r.recorded_at, offset_minutes),
                str(r.systolic),
                str(r.diastolic),
                "" if r.pulse is None else str(r.pulse),
                Paragraph(_text(r.notes), cell_style),
            ]
            for r in shown_bp
        ]
        story.append(
            _readings_table(
                ["Date and time", "Systolic", "Diastolic", "Pulse", "Notes"],
                rows_bp,
                [38 * mm, 22 * mm, 22 * mm, 18 * mm, 74 * mm],
            )
        )

    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(DISCLAIMER, small_style))

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title="MediTrack AI Health Report",
        author="MediTrack AI",
        pageCompression=1 if compress else 0,
    )
    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()