"""Movement progress report -> PDF.

Lays out a frozen MOVEMENT_PROGRESS report payload. It draws only what the
payload holds; nothing is recomputed here. Every page carries the provenance
banner, the research-prototype notice and, for generated or replayed data, a
watermark, so a single printed page cannot be mistaken for clinical evidence.
"""

from __future__ import annotations

import math
from datetime import datetime

from app.services.pdf import PdfDocument, text_width, wrap

INK = "#1d2733"
MUTED = "#5b6876"
FAINT = "#c9d1da"
GRID = "#e6eaef"
TEAL = "#0f766e"
BLUE = "#1f6feb"
VIOLET = "#6d4fd6"
AMBER_BG = "#fff4d6"
AMBER_INK = "#7a4b00"
RED = "#b42318"
MARGIN = 44.0

EXERCISE = {"WALK": "Walking", "SQUAT": "Squat", "SIT_TO_STAND": "Sit-to-stand", "STEP_UP": "Step-up",
            "KNEE_EXTENSION": "Knee extension", "SINGLE_LEG_BALANCE": "Single-leg balance"}
STATUS_TEXT = {"IMPROVING": "Improving", "STABLE": "Stable", "NEEDS_ATTENTION": "Needs attention",
               "COMPLETED": "Programme completed"}
ACTIVITY = {"other_exercise": "other exercise", "stairs_up": "stairs up", "stairs_down": "stairs down"}


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _date(value: str | None, fmt: str = "%d %b %Y") -> str:
    d = _dt(value) if value and "T" in value else None
    if d is None and value:
        try:
            d = datetime.fromisoformat(value)
        except ValueError:
            return value
    return d.strftime(fmt) if d else "—"


def _f(value, digits: int = 1, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}{suffix}"


def _signed(value, digits: int = 1, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value:+.{digits}f}{suffix}"


def _duration(seconds) -> str:
    if seconds is None:
        return "—"
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}"


def _line_chart(doc: PdfDocument, x: float, y: float, w: float, h: float, series: list[tuple[datetime, float]],
                *, lo: float, hi: float, color: str, title: str, unit: str, note: str | None = None) -> None:
    doc.text(x, y, title, size=9.5, font="F2", color=INK)
    if note:
        doc.text(x + w, y, note, size=7.5, color=MUTED, align="right")
    top = y + 10
    plot_x, plot_w = x + 30, w - 34
    plot_h = h - 26
    doc.rect(plot_x, top, plot_w, plot_h, stroke=FAINT, width=0.5)
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        yy = top + plot_h - plot_h * k / 4
        if 0 < k < 4:
            doc.line(plot_x, yy, plot_x + plot_w, yy, width=0.4, color=GRID)
        doc.text(plot_x - 4, yy + 2.5, f"{v:.0f}{unit}", size=7, color=MUTED, align="right")
    if not series:
        doc.text(plot_x + plot_w / 2, top + plot_h / 2, "No values recorded", size=8.5, color=MUTED, align="center")
        return
    t0 = series[0][0].timestamp()
    t1 = series[-1][0].timestamp()
    span = max(1.0, t1 - t0)

    def px(t: datetime) -> float:
        return plot_x + 6 + (plot_w - 12) * (t.timestamp() - t0) / span

    def py(v: float) -> float:
        v = min(hi, max(lo, v))
        return top + plot_h - plot_h * (v - lo) / (hi - lo)

    pts = [(px(t), py(v)) for t, v in series]
    doc.polyline(pts, width=1.3, color=color)
    for p in pts:
        doc.dot(p[0], p[1], 1.9, color=color)
    # Date ticks: first, last and up to three between.
    n = len(series)
    ticks = sorted({0, n - 1, *[round(i * (n - 1) / 4) for i in range(1, 4)]})
    last_x = -1e9
    for i in ticks:
        tx = px(series[i][0])
        if tx - last_x < 44 and i not in (0, n - 1):
            continue
        doc.line(tx, top + plot_h, tx, top + plot_h + 3, width=0.5, color=FAINT)
        doc.text(tx, top + plot_h + 12, series[i][0].strftime("%d %b"), size=7, color=MUTED, align="center")
        last_x = tx


def _kv(doc: PdfDocument, x: float, y: float, key: str, value: str, width: float) -> None:
    doc.text(x, y, key.upper(), size=6.8, font="F2", color=MUTED)
    lines = wrap(value, 9.5, width, "F1")[:2]
    for i, line in enumerate(lines):
        doc.text(x, y + 12 + i * 11, line, size=9.5, color=INK)


def render_movement_report(payload: dict, *, report_id: int | None = None) -> bytes:
    patient = payload.get("patient") or {}
    sm = payload.get("summary") or {}
    labels = payload.get("labels") or {}
    sessions = payload.get("sessions") or []
    provenance = payload.get("provenance")
    banner = labels.get("provenance") or "RESEARCH PROTOTYPE OUTPUT — NOT CLINICAL EVIDENCE"
    generated = _date(payload.get("generated_at"), "%d %b %Y %H:%M UTC")
    generated_data = provenance in ("SYNTHETIC_DEMONSTRATION", "PUBLIC_DATASET_REPLAY", "SIMULATED")
    doc = PdfDocument(title=f"{payload.get('title', 'Movement progress report')} — {patient.get('name', '')}")
    W, H = doc.width, doc.height
    content_w = W - 2 * MARGIN

    def watermark(d: PdfDocument, index: int, total: int) -> None:
        if not generated_data:
            return
        word = "SYNTHETIC DEMONSTRATION" if provenance == "SYNTHETIC_DEMONSTRATION" else "PUBLIC DATASET REPLAY"
        size, angle = 40.0, 35.0
        w = text_width(word, size, "F2")
        a = math.radians(angle)
        # Centred on the page: start half the text length back along the slope.
        x0 = W / 2 - (w / 2) * math.cos(a)
        y0 = H / 2 + (w / 2) * math.sin(a)
        d.rotated_text(x0, y0, word, angle=angle, size=size, color="#f0f2f5")

    def chrome(d: PdfDocument, index: int, total: int) -> None:
        d.rect(0, 0, W, 24, fill=AMBER_BG)
        d.line(0, 24, W, 24, width=0.8, color="#e7c46a")
        d.text(MARGIN, 15.5, banner, size=8.6, font="F2", color=AMBER_INK)
        d.text(W - MARGIN, 15.5, "RehabSense · research prototype", size=7.8, color=AMBER_INK, align="right")
        d.line(MARGIN, H - 40, W - MARGIN, H - 40, width=0.5, color=FAINT)
        d.text(MARGIN, H - 28, "RehabSense is a research prototype and not a medical device.",
               size=7.8, font="F2", color=INK)
        d.text(MARGIN, H - 17, f"Not a medical record · Report {report_id or '—'} · generated {generated} · "
               f"{payload.get('report_version', '')}", size=7, color=MUTED)
        d.text(W - MARGIN, H - 28, f"Page {index + 1} of {total}", size=7.8, color=MUTED, align="right")

    doc.page_hooks += [(watermark, "under"), (chrome, "over")]

    # ------------------------------------------------------------ page 1
    doc.add_page()
    y = 52.0
    doc.text(MARGIN, y, "REHABSENSE", size=8.5, font="F2", color=TEAL)
    doc.text(MARGIN, y + 24, payload.get("title", "Movement progress report"), size=21, font="F2", color=INK)
    doc.text(MARGIN, y + 40, "Hardware protocol v2 · two shank IMUs + heel force · research indicators",
             size=9, color=MUTED)

    # Record block
    y = 108.0
    doc.rect(MARGIN, y, content_w, 70, fill="#f7f9fb", stroke=FAINT, width=0.5)
    col = content_w / 4
    period = f"{_date(payload.get('period', {}).get('first_session'), '%d %b')} – " \
             f"{_date(payload.get('period', {}).get('end'), '%d %b %Y')}"
    days = (payload.get("period") or {}).get("days")
    planned = sm.get("planned_sessions")
    _kv(doc, MARGIN + 10, y + 16, "Record", patient.get("name") or "—", col - 16)
    _kv(doc, MARGIN + 10 + col, y + 16, "Programme", patient.get("program") or "—", col - 16)
    _kv(doc, MARGIN + 10 + 2 * col, y + 16, "Period", f"{period} ({days} days)" if days else period, col - 16)
    _kv(doc, MARGIN + 10 + 3 * col, y + 16, "Sessions",
        f"{sm.get('sessions_completed', 0)}" + (f" of {planned} planned" if planned else ""), col - 16)
    doc.line(MARGIN + 10, y + 44, MARGIN + content_w - 10, y + 44, width=0.4, color=GRID)
    doc.text(MARGIN + 10, y + 58,
             f"Status: {STATUS_TEXT.get(sm.get('status'), sm.get('status') or '—')}"
             f"   ·   Adherence: {_f(sm.get('adherence_pct'), 0, '%')}"
             f"   ·   Operated side: {(patient.get('operated_leg') or '—').title()}"
             f"   ·   Data provenance: {(provenance or 'RECORDED').replace('_', ' ')}",
             size=8.6, color=INK)

    # KPI tiles
    y = 192.0
    gap = 8.0
    tw = (content_w - 3 * gap) / 4
    tiles = [
        ("MOVEMENT QUALITY (MQI)", (_f(sm.get("initial_mqi")), _f(sm.get("current_mqi"))),
         f"{_signed(sm.get('mqi_change'))} points ({_signed(sm.get('improvement_pct'), 0, '%')})", TEAL),
        ("ASYMMETRY", (_f(sm.get("initial_asymmetry_pct"), 1, "%"), _f(sm.get("current_asymmetry_pct"), 1, "%")),
         f"{_signed(sm.get('asymmetry_change_pct'))} points (lower = more alike)", VIOLET),
        ("TREND", STATUS_TEXT.get(sm.get("status"), "—"),
         f"MQI {_signed(sm.get('mqi_slope_per_week'), 2)} per week",
         {"IMPROVING": TEAL, "NEEDS_ATTENTION": "#d97706", "COMPLETED": BLUE}.get(sm.get("status"), MUTED)),
        ("SIGNAL CONFIDENCE", _f(sm.get("mean_confidence_pct"), 0, "%"),
         f"consistency SD {_f(sm.get('consistency_sd'))} (last 6)", MUTED),
    ]
    for i, (label, value, sub, color) in enumerate(tiles):
        tx = MARGIN + i * (tw + gap)
        doc.rect(tx, y, tw, 58, stroke=FAINT, width=0.5)
        doc.rect(tx, y, 3, 58, fill=color)
        doc.text(tx + 10, y + 14, label, size=6.8, font="F2", color=MUTED)
        if isinstance(value, tuple):
            # start -> current, with a drawn arrow (no arrow glyph in WinAnsi)
            first, second = value
            doc.text(tx + 10, y + 33, first, size=13, font="F2", color=MUTED)
            ax = tx + 10 + text_width(first, 13, "F2") + 5
            doc.line(ax, y + 28.5, ax + 12, y + 28.5, width=1.1, color=MUTED)
            doc.polyline([(ax + 8.5, y + 25.5), (ax + 12, y + 28.5), (ax + 8.5, y + 31.5)], width=1.1, color=MUTED)
            doc.text(ax + 17, y + 33, second, size=13, font="F2", color=INK)
        else:
            doc.text(tx + 10, y + 33, value, size=13, font="F2", color=INK)
        doc.text(tx + 10, y + 48, sub, size=7.2, color=MUTED)

    doc.text(MARGIN, y + 72, "Start = mean of the first two sessions; current = mean of the last two.",
             size=7.5, color=MUTED)

    mqi_series = [(t, s["mqi"]) for s in sessions if s.get("mqi") is not None and (t := _dt(s["started_at"]))]
    asym_series = [(t, s["asymmetry_pct"]) for s in sessions
                   if s.get("asymmetry_pct") is not None and (t := _dt(s["started_at"]))]
    lo = min([v for _, v in mqi_series] + [60.0]) // 10 * 10
    _line_chart(doc, MARGIN, 290, content_w, 170, mqi_series, lo=max(0.0, lo), hi=100.0, color=TEAL,
                title="Movement quality per session (MQI, 0–100)", unit="",
                note="Research metric · mqi-proto-v1 · not clinically validated")
    top = max([v for _, v in asym_series] + [20.0])
    _line_chart(doc, MARGIN, 482, content_w, 140, asym_series, lo=0.0, hi=float(int(top // 10 + 1) * 10),
                color=VIOLET, title="Bilateral asymmetry per session (%)", unit="%",
                note="0 = left and right move alike · segment tilt, not a joint angle")

    # Activity distribution (model output)
    y = 646.0
    doc.text(MARGIN, y, "Activity model output (share of classified time)", size=9.5, font="F2", color=INK)
    models = ", ".join(payload.get("models") or []) or "unavailable"
    doc.text(W - MARGIN, y, f"Model {models} · public-dataset trained", size=7.5, color=MUTED, align="right")
    acts = payload.get("activity_distribution") or {}
    total = sum(acts.values()) or 1.0
    bar_x, bar_w = MARGIN + 92, content_w - 140
    for i, (name, secs) in enumerate(list(acts.items())[:5]):
        yy = y + 16 + i * 15
        share = secs / total
        doc.text(MARGIN, yy + 7, ACTIVITY.get(name, name.replace("_", " ")), size=8.5, color=INK)
        doc.rect(bar_x, yy, bar_w, 9, fill="#eef2f6")
        doc.rect(bar_x, yy, max(1.0, bar_w * share), 9, fill=BLUE)
        doc.text(bar_x + bar_w + 6, yy + 7.5, "<1%" if share < 0.005 else f"{share * 100:.0f}%",
                 size=8, color=MUTED)
    if not acts:
        doc.text(MARGIN, y + 22, "No classified windows.", size=8.5, color=MUTED)
    doc.text(MARGIN, y + 98, "A model result on these signals, not an observation of what the person did.",
             size=7.5, color=MUTED)

    # ------------------------------------------------------------ page 2
    doc.add_page()
    y = 52.0
    doc.text(MARGIN, y, "Session history", size=13, font="F2", color=INK)
    best, worst = sm.get("best_session") or {}, sm.get("worst_session") or {}
    doc.text(MARGIN, y + 16, f"Best: {_f(best.get('mqi'))} on {_date(best.get('started_at'), '%d %b')} "
             f"({EXERCISE.get(best.get('exercise_type'), '—')}) · Worst: {_f(worst.get('mqi'))} on "
             f"{_date(worst.get('started_at'), '%d %b')} ({EXERCISE.get(worst.get('exercise_type'), '—')}) · "
             f"{_f(sm.get('sessions_per_week'), 1)} sessions per week", size=8.4, color=MUTED)
    cols = [("Date", 54, "left"), ("Day", 26, "right"), ("Exercise", 70, "left"), ("Time", 34, "right"),
            ("Reps", 30, "right"), ("MQI", 36, "right"), ("Asym.", 40, "right"), ("Conf.", 36, "right"),
            ("Calib.", 42, "left"), ("Model activity", 0, "left")]
    used = sum(c[1] for c in cols)
    cols[-1] = (cols[-1][0], content_w - used, "left")
    y += 34
    doc.rect(MARGIN, y - 10, content_w, 15, fill="#eef2f6")
    cx = MARGIN + 4
    for name, width, align in cols:
        doc.text(cx + (width - 8 if align == "right" else 0), y, name, size=7.4, font="F2", color=MUTED,
                 align=align)
        cx += width
    y += 14
    row_h = 13.2
    for idx, s in enumerate(sessions):
        if y > H - 70:
            doc.add_page()
            y = 52.0
        if idx % 2 == 1:
            doc.rect(MARGIN, y - 9.5, content_w, row_h, fill="#f8fafc")
        values = [_date(s.get("started_at"), "%d %b"), str(s.get("programme_day") or "—"),
                  EXERCISE.get(s.get("exercise_type"), s.get("exercise_type") or "—"), _duration(s.get("duration_s")),
                  str(s.get("repetitions") if s.get("repetitions") is not None else "—"), _f(s.get("mqi")),
                  _f(s.get("asymmetry_pct"), 1, "%"), _f(s.get("confidence_pct"), 0, "%"),
                  (s.get("calibration_status") or "—").title(),
                  ACTIVITY.get(s.get("activity_top") or "", (s.get("activity_top") or "—").replace("_", " "))]
        cx = MARGIN + 4
        for (name, width, align), value in zip(cols, values):
            doc.text(cx + (width - 8 if align == "right" else 0), y, value, size=8, color=INK, align=align)
            cx += width
        y += row_h

    # Method, provenance, definitions
    y += 16
    if y > H - 260:
        doc.add_page()
        y = 52.0
    doc.text(MARGIN, y, "How these figures were produced", size=11, font="F2", color=INK)
    y += 16
    method = (
        "Each session was streamed through the RehabSense hardware-v2 pipeline (stream checks, device "
        "calibration, windowing, activity model, bilateral asymmetry, repetition detection, Movement "
        "Quality Index) and stored; this report reads those stored results and recomputes none of them.")
    y = doc.paragraph(MARGIN, y, method, width=content_w, size=8.6, color=INK)
    detail = (labels.get("provenance_detail") or "").replace(" -- ", " — ")
    if detail:
        y = doc.paragraph(MARGIN, y + 2, f"Data provenance: {detail}.", width=content_w, size=8.6, color=INK)
    gen = (payload.get("clinical") or {}).get("generation")
    if gen:
        y = doc.paragraph(MARGIN, y + 2,
                          f"Generator: {gen.get('generator')} {gen.get('synthetic_generator_version')}, seed "
                          f"{gen.get('seed')}; source data: {gen.get('source_dataset')}; model "
                          f"{gen.get('model_version')}; pipeline {gen.get('pipeline_version')}; trajectory "
                          f"design {gen.get('trajectory')}. The trend comes from the designed generator inputs, "
                          "measured by the unchanged pipeline.",
                          width=content_w, size=8.2, color=MUTED)
    for key in ("mqi", "asymmetry", "activity"):
        text = (payload.get("definitions") or {}).get(key)
        if text:
            y = doc.paragraph(MARGIN, y + 2, f"{key.upper()}: {text}", width=content_w, size=8.2, color=MUTED)
    rule = payload.get("status_rule") or {}
    if rule:
        basis = rule.get("basis", "")
        basis = basis[:1].upper() + basis[1:]
        y = doc.paragraph(MARGIN, y + 2, f"Status rule — needs attention when {rule.get('NEEDS_ATTENTION')}; "
                          f"improving when {rule.get('IMPROVING')}. {basis}.",
                          width=content_w, size=8.2, color=MUTED)
    notes = (payload.get("clinical") or {}).get("notes")
    if notes:
        y += 6
        doc.text(MARGIN, y, "Clinician notes", size=9.5, font="F2", color=INK)
        y = doc.paragraph(MARGIN, y + 13, notes, width=content_w, size=8.4, color=INK)

    # Disclaimers
    y += 10
    lines = []
    for d in payload.get("disclaimers") or []:
        lines += wrap(d, 9, content_w - 24, "F2")
    box_h = 18 + 12.5 * len(lines)
    if y + box_h > H - 50:
        doc.add_page()
        y = 52.0
    doc.rect(MARGIN, y, content_w, box_h, fill=AMBER_BG, stroke="#e7c46a", width=0.6)
    yy = y + 16
    for line in lines:
        doc.text(MARGIN + 12, yy, line, size=9, font="F2", color=AMBER_INK)
        yy += 12.5
    return doc.render()
