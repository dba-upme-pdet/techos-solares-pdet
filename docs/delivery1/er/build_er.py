"""Genera diagrama_er.svg (notación pata de gallo) a partir de la definición de abajo.

Uso:  python docs/delivery1/er/build_er.py
Las entidades y campos siguen el diccionario de datos de la Entrega 1.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
W, HEAD, ROW, PAD = 300, 36, 26, 8
FONT = "Inter, 'Helvetica Neue', Helvetica, Arial, 'Liberation Sans', sans-serif"
INK, MUTED, LINE, ACCENT, HEADER = "#1E293B", "#64748B", "#475569", "#1F5FAF", "#1E293B"

# nombre: (x, y, [(clave, campo, tipo, índice)])
ENTITIES = {
    "PDET_SUBREGION": (30, 40, [
        ("PK", "_id", "int", ""), ("", "name", "string", ""),
        ("", "municipality_count", "int", "")]),
    "MUNICIPALITY": (440, 40, [
        ("PK", "_id", "string(5)", ""), ("FK", "subregion_id", "int", ""),
        ("", "name", "string", ""), ("", "dpto_code", "string(2)", ""),
        ("", "area_km2", "double", ""), ("", "geometry", "MultiPolygon", "2dsphere")]),
    "ROOFTOP_STAT": (850, 40, [
        ("PK FK", "_id.mpio_code", "string(5)", ""), ("PK FK", "_id.dataset_id", "string", ""),
        ("", "building_count", "int", ""), ("", "total_area_m2", "double", ""),
        ("", "median_area_m2", "double", "")]),
    "INGESTION_RUN": (30, 360, [
        ("PK", "_id", "ObjectId", ""), ("FK", "dataset_id", "string", ""),
        ("", "source_file", "string", ""), ("", "rows_loaded", "int", ""),
        ("", "rows_rejected", "int", "")]),
    "BUILDING": (440, 360, [
        ("PK", "_id", "ObjectId", ""), ("FK", "dataset_id", "string", ""),
        ("FK", "mpio_code", "string(5)", ""), ("FK", "run_id", "ObjectId", ""),
        ("", "footprint", "Polygon", ""), ("", "centroid", "Point", "2dsphere"),
        ("", "area_m2", "double", ""), ("", "confidence", "double", "")]),
    "DATASET": (850, 360, [
        ("PK", "_id", "string", ""), ("", "name", "string", ""),
        ("", "version", "string", ""), ("", "license", "string", "")]),
}


def box(name):
    x, y, rows = ENTITIES[name]
    return x, y, W, HEAD + len(rows) * ROW + PAD


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;")


def entity_svg(name):
    x, y, w, h = box(name)
    out = [f'<g><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" fill="#FFFFFF" stroke="#CBD5E1"/>',
           f'<path d="M{x} {y+7}a7 7 0 0 1 7-7h{w-14}a7 7 0 0 1 7 7v{HEAD-7}h-{w}z" fill="{HEADER}"/>',
           f'<text x="{x+14}" y="{y+23}" font-size="14" font-weight="700" fill="#FFFFFF" letter-spacing="0.4">{name}</text>']
    for i, (key, field, typ, idx) in enumerate(ENTITIES[name][2]):
        ry = y + HEAD + i * ROW
        if i % 2:
            out.append(f'<rect x="{x+1}" y="{ry}" width="{w-2}" height="{ROW}" fill="#F8FAFC"/>')
        ty = ry + 17
        if key:
            out.append(f'<text x="{x+14}" y="{ty}" font-size="10" font-weight="700" fill="{ACCENT}">{key}</text>')
        weight = "600" if "PK" in key else "400"
        out.append(f'<text x="{x+64}" y="{ty}" font-size="13" font-weight="{weight}" fill="{INK}">{esc(field)}</text>')
        out.append(f'<text x="{x+w-14}" y="{ty}" font-size="12" fill="{MUTED}" text-anchor="end">{esc(typ)}</text>')
        if idx:
            tw = 62
            px = x + w - 14 - len(typ) * 6.9 - tw - 8
            out.append(f'<rect x="{px}" y="{ry+5}" width="{tw}" height="16" rx="8" fill="#E8F0FB"/>'
                       f'<text x="{px+tw/2}" y="{ry+16.5}" font-size="10" fill="{ACCENT}" text-anchor="middle">{idx}</text>')
    out.append("</g>")
    return "\n".join(out)


def marker(px, py, dx, dy, kind):
    """Extremo de relación en (px, py); (dx, dy) apunta desde la entidad hacia la línea."""
    nx, ny = -dy, dx
    at = lambda d, s=0: (px + dx * d + nx * s, py + dy * d + ny * s)
    seg = lambda a, b: f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}"/>'
    parts = []
    many = kind.endswith("many")
    if many:  # pata de gallo: puntas sobre el borde, vértice a 14 px
        apex = at(14)
        parts += [seg(apex, at(0, -9)), seg(apex, at(0, 9)), seg(apex, at(0))]
    if kind == "one":          # exactamente uno: dos barras
        parts += [seg(at(10, -7), at(10, 7)), seg(at(16, -7), at(16, 7))]
    elif kind == "one_many":   # uno o muchos
        parts += [seg(at(20, -7), at(20, 7))]
    elif kind == "zero_many":  # cero o muchos
        c = at(23)
        parts += [f'<circle cx="{c[0]}" cy="{c[1]}" r="5" fill="#FFFFFF"/>']
    elif kind == "zero_one":   # cero o uno
        c = at(20)
        parts += [seg(at(10, -7), at(10, 7)), f'<circle cx="{c[0]}" cy="{c[1]}" r="5" fill="#FFFFFF"/>']
    return "".join(parts)


def label(x, y, text):
    w = len(text) * 6.6 + 14
    return (f'<rect x="{x-w/2}" y="{y-10}" width="{w}" height="20" rx="4" fill="#FFFFFF"/>'
            f'<text x="{x}" y="{y+4}" font-size="12" font-style="italic" fill="{MUTED}" text-anchor="middle">{text}</text>')


def relations():
    sx, sy, sw, sh = box("PDET_SUBREGION")
    mx, my, mw, mh = box("MUNICIPALITY")
    rx, ry, rw, rh = box("ROOFTOP_STAT")
    ix, iy, iw, ih = box("INGESTION_RUN")
    bx, by, bw, bh = box("BUILDING")
    dx, dy, dw, dh = box("DATASET")
    top = my + HEAD + ROW // 2           # fila del _id
    low = by + HEAD + ROW // 2
    bottom = max(bh + by, ih + iy, dh + dy) + 44
    paths, marks, labels = [], [], []

    def edge(points, start, end, text, at):
        paths.append("M" + " L".join(f"{p[0]} {p[1]}" for p in points))
        (x0, y0), (x1, y1) = points[0], points[1]
        marks.append(marker(x0, y0, (x1 > x0) - (x1 < x0), (y1 > y0) - (y1 < y0), start))
        (x0, y0), (x1, y1) = points[-1], points[-2]
        marks.append(marker(x0, y0, (x1 > x0) - (x1 < x0), (y1 > y0) - (y1 < y0), end))
        labels.append(label(*at, text))

    edge([(sx + sw, top), (mx, top)], "one", "one_many", "agrupa", ((sx + sw + mx) / 2, top - 18))
    edge([(mx + mw, top), (rx, top)], "one", "zero_many", "resume", ((mx + mw + rx) / 2, top - 18))
    cx = mx + mw / 2
    edge([(cx, my + mh), (cx, by)], "zero_one", "zero_many", "contiene (centroide)", (cx, (my + mh + by) / 2))
    dcx = dx + dw / 2
    edge([(dcx, dy), (dcx, ry + rh)], "one", "zero_many", "mide", (dcx, (dy + ry + rh) / 2))
    edge([(dx, low), (bx + bw, low)], "one", "zero_many", "provee", ((dx + bx + bw) / 2, low - 18))
    edge([(ix + iw, low), (bx, low)], "one", "zero_many", "inserta", ((ix + iw + bx) / 2, low - 18))
    icx = ix + iw / 2
    edge([(dcx, dy + dh), (dcx, bottom), (icx, bottom), (icx, iy + ih)], "one", "zero_many",
         "registra", ((dcx + icx) / 2, bottom))
    return paths, marks, labels, bottom


def legend(y):
    items = [("one", "exactamente uno"), ("zero_one", "cero o uno"),
             ("one_many", "uno o muchos"), ("zero_many", "cero o muchos")]
    out, x = [], 30
    for kind, text in items:
        out.append(f'<g stroke="{LINE}" stroke-width="1.4" fill="none"><line x1="{x}" y1="{y}" x2="{x+44}" y2="{y}"/>'
                   f'{marker(x+44, y, -1, 0, kind)}</g>'
                   f'<text x="{x+54}" y="{y+4}" font-size="12" fill="{MUTED}">{text}</text>')
        x += 190
    return "".join(out)


def main():
    paths, marks, labels, bottom = relations()
    height = bottom + 64
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1180" height="{height}" viewBox="0 0 1180 {height}" font-family="{FONT}">',
           f'<rect width="1180" height="{height}" fill="#FFFFFF"/>',
           f'<g stroke="{LINE}" stroke-width="1.4" fill="none">' + "".join(f'<path d="{p}"/>' for p in paths) + "</g>",
           f'<g stroke="{LINE}" stroke-width="1.4" fill="none">' + "".join(marks) + "</g>",
           *[entity_svg(n) for n in ENTITIES],
           *labels,
           legend(height - 26),
           "</svg>"]
    (HERE.parent / "diagrama_er.svg").write_text("\n".join(svg), encoding="utf-8")
    print("escrito", HERE.parent / "diagrama_er.svg")


if __name__ == "__main__":
    main()
