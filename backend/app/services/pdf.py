"""A small, dependency-free PDF writer for RehabSense reports.

Text in the PDF standard fonts (Helvetica, Helvetica-Bold, Courier) with
WinAnsi encoding, plus lines, rectangles and polylines -- enough for a
report with charts and tables, without adding an imaging stack to the API
image. Coordinates are in points from the TOP-left corner of the page.
"""

from __future__ import annotations

import math
import zlib
from datetime import datetime, timezone

A4 = (595.28, 841.89)

# Helvetica / Helvetica-Bold advance widths (1/1000 em) for ASCII 32-126,
# from the standard Adobe font metrics.
_HELV = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
         556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
         1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
         667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
         333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
         556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]
_HELV_BOLD = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,
              556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611,
              975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
              667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556,
              333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,
              611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584]
_EXTRA = {"—": 1000, "–": 556, "·": 278, "°": 400, "×": 584, "±": 584, "’": 222, "‘": 222,
          "“": 333, "”": 333, "…": 1000, "•": 350}
# Characters outside WinAnsi that reports use, mapped to safe equivalents.
_TRANSLATE = str.maketrans({"−": "-", "≥": ">=", "≤": "<=", "→": "->", "←": "<-", "≈": "~",
                            "✓": "v", "✗": "x", "∆": "D", "Δ": "D", " ": " ", " ": " "})

FONTS = {"F1": "Helvetica", "F2": "Helvetica-Bold", "F3": "Courier"}


def _clean(text: str) -> str:
    return str(text).translate(_TRANSLATE)


def text_width(text: str, size: float, font: str = "F1") -> float:
    text = _clean(text)
    if font == "F3":
        return 0.6 * size * len(text)
    table = _HELV_BOLD if font == "F2" else _HELV
    total = 0
    for ch in text:
        o = ord(ch)
        total += table[o - 32] if 32 <= o <= 126 else _EXTRA.get(ch, 556)
    return total * size / 1000.0


def wrap(text: str, size: float, width: float, font: str = "F1") -> list[str]:
    lines: list[str] = []
    for para in _clean(text).split("\n"):
        words = para.split(" ")
        line = ""
        for word in words:
            trial = word if not line else f"{line} {word}"
            if text_width(trial, size, font) <= width or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def _escape(text: str) -> bytes:
    raw = _clean(text).encode("cp1252", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _rgb(color) -> str:
    if isinstance(color, str):
        color = color.lstrip("#")
        color = tuple(int(color[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return " ".join(f"{c:.3f}" for c in color)


class PdfDocument:
    def __init__(self, *, title: str, size: tuple[float, float] = A4, author: str = "RehabSense") -> None:
        self.title = title
        self.author = author
        self.width, self.height = size
        self.pages: list[list[bytes]] = []
        # (callable(doc, page_index, page_count), "under" | "over"): drawn on
        # every page at render time -- headers, footers, watermarks.
        self.page_hooks: list[tuple] = []
        self._target: list[bytes] | None = None

    # -------------------------------------------------------------- pages
    def add_page(self) -> None:
        self.pages.append([])

    @property
    def _ops(self) -> list[bytes]:
        if self._target is not None:
            return self._target
        if not self.pages:
            self.add_page()
        return self.pages[-1]

    def _y(self, y: float) -> float:
        return self.height - y

    # ------------------------------------------------------------ drawing
    def text(self, x: float, y: float, text: str, *, size: float = 10, font: str = "F1",
             color="#1d2733", align: str = "left") -> None:
        """Baseline at y (from the top)."""
        if align != "left":
            w = text_width(text, size, font)
            x = x - w if align == "right" else x - w / 2
        self._ops.append(b"BT /" + font.encode() + f" {size:.2f} Tf {_rgb(color)} rg "
                         f"{x:.2f} {self._y(y):.2f} Td (".encode() + _escape(text) + b") Tj ET")

    def rotated_text(self, x: float, y: float, text: str, *, angle: float, size: float,
                     font: str = "F2", color="#eef1f4") -> None:
        a = math.radians(angle)
        c, s = math.cos(a), math.sin(a)
        self._ops.append(b"BT /" + font.encode() + f" {size:.2f} Tf {_rgb(color)} rg "
                         f"{c:.4f} {s:.4f} {-s:.4f} {c:.4f} {x:.2f} {self._y(y):.2f} Tm (".encode()
                         + _escape(text) + b") Tj ET")

    def paragraph(self, x: float, y: float, text: str, *, width: float, size: float = 9.5,
                  font: str = "F1", color="#1d2733", leading: float | None = None) -> float:
        """Wrapped text from baseline y; returns the y after the last line."""
        leading = leading or size * 1.38
        for line in wrap(text, size, width, font):
            self.text(x, y, line, size=size, font=font, color=color)
            y += leading
        return y

    def line(self, x1: float, y1: float, x2: float, y2: float, *, width: float = 0.6,
             color="#c9d1da", dash: tuple[float, float] | None = None) -> None:
        d = f"[{dash[0]} {dash[1]}] 0 d " if dash else "[] 0 d "
        self._ops.append(f"q {d}{width:.2f} w {_rgb(color)} RG {x1:.2f} {self._y(y1):.2f} m "
                         f"{x2:.2f} {self._y(y2):.2f} l S Q".encode())

    def rect(self, x: float, y: float, w: float, h: float, *, fill=None, stroke=None,
             width: float = 0.6) -> None:
        """Top-left corner at (x, y)."""
        parts = ["q"]
        if fill is not None:
            parts.append(f"{_rgb(fill)} rg")
        if stroke is not None:
            parts.append(f"{width:.2f} w {_rgb(stroke)} RG")
        parts.append(f"{x:.2f} {self._y(y + h):.2f} {w:.2f} {h:.2f} re")
        parts.append("B" if fill is not None and stroke is not None else "f" if fill is not None else "S")
        parts.append("Q")
        self._ops.append(" ".join(parts).encode())

    def polyline(self, points: list[tuple[float, float]], *, width: float = 1.2, color="#1f6feb") -> None:
        if len(points) < 2:
            return
        path = [f"{points[0][0]:.2f} {self._y(points[0][1]):.2f} m"]
        path += [f"{x:.2f} {self._y(y):.2f} l" for x, y in points[1:]]
        self._ops.append(f"q [] 0 d 1 J 1 j {width:.2f} w {_rgb(color)} RG {' '.join(path)} S Q".encode())

    def dot(self, x: float, y: float, r: float = 1.8, *, color="#1f6feb") -> None:
        k = 0.5523 * r
        cy = self._y(y)
        self._ops.append((f"q {_rgb(color)} rg {x + r:.2f} {cy:.2f} m "
                          f"{x + r:.2f} {cy + k:.2f} {x + k:.2f} {cy + r:.2f} {x:.2f} {cy + r:.2f} c "
                          f"{x - k:.2f} {cy + r:.2f} {x - r:.2f} {cy + k:.2f} {x - r:.2f} {cy:.2f} c "
                          f"{x - r:.2f} {cy - k:.2f} {x - k:.2f} {cy - r:.2f} {x:.2f} {cy - r:.2f} c "
                          f"{x + k:.2f} {cy - r:.2f} {x + r:.2f} {cy - k:.2f} {x + r:.2f} {cy:.2f} c f Q").encode())

    # ------------------------------------------------------------- output
    def render(self) -> bytes:
        total = len(self.pages)
        for index in range(total):
            for hook, layer in self.page_hooks:
                self._target = []
                hook(self, index, total)
                if layer == "under":
                    self.pages[index][:0] = self._target
                else:
                    self.pages[index].extend(self._target)
        self._target = None
        objects: list[bytes] = []

        def add(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        catalog = add(b"")          # 1, filled below
        pages_obj = add(b"")        # 2
        font_ids = {name: add(f"<< /Type /Font /Subtype /Type1 /BaseFont /{base} "
                              f"/Encoding /WinAnsiEncoding >>".encode())
                    for name, base in FONTS.items()}
        fonts = " ".join(f"/{n} {i} 0 R" for n, i in font_ids.items())
        kids = []
        for ops in self.pages:
            stream = zlib.compress(b"\n".join(ops), 9)
            content = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream)
                          + stream + b"\nendstream")
            kids.append(add(f"<< /Type /Page /Parent {pages_obj} 0 R /MediaBox [0 0 {self.width:.2f} "
                            f"{self.height:.2f}] /Resources << /Font << {fonts} >> >> "
                            f"/Contents {content} 0 R >>".encode()))
        objects[catalog - 1] = f"<< /Type /Catalog /Pages {pages_obj} 0 R >>".encode()
        objects[pages_obj - 1] = (f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] "
                                  f"/Count {len(kids)} >>").encode()
        stamp = datetime.now(timezone.utc).strftime("D:%Y%m%d%H%M%SZ")
        info = add(b"<< /Title (" + _escape(self.title) + b") /Author (" + _escape(self.author)
                   + b") /Producer (RehabSense report renderer) /CreationDate (" + stamp.encode() + b") >>")

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for number, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
        for off in offsets:
            out += f"{off:010d} 00000 n \n".encode()
        out += (f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\n"
                f"startxref\n{xref}\n%%EOF\n").encode()
        return bytes(out)
