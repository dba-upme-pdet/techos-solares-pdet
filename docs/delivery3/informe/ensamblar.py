"""Une el resumen y las secciones de docs/delivery3 en un solo Markdown autocontenido."""
import re, sys
from pathlib import Path

SECCIONES = [  # (archivo, título numerado)
    ("entrega3_descarga_microsoft.md", "5. Descarga de Microsoft Building Footprints"),
    ("entrega3_descarga_google.md", "6. Descarga de Google Open Buildings v3"),
    ("entrega3_preparacion_huellas.md", "7. Preparación de huellas de edificaciones"),
    ("entrega3_carga_buildings.md", "8. Carga de huellas en MongoDB e índices espaciales"),
]
# Secciones internas de coordinación del equipo: no van al informe.
OMITIR = ("Entrega a Derek", "Samuel / EDA", "Cierre y traspaso", "División del trabajo",
          "Pendiente del tramo", "Interfaces para el resto", "Cargador de Samuel")

DIAGRAMAS = []

def diagramas(texto):
    """Cambia cada bloque mermaid por una figura; build.sh la dibuja con mermaid-cli."""
    def figura(m):
        DIAGRAMAS.append(m.group(1))
        return f"![Flujo de la preparación de huellas.](diagrama{len(DIAGRAMAS)}.png){{width=100%}}"
    return re.sub(r"```mermaid\n(.*?)```", figura, texto, flags=re.S)

def seccion(texto, titulo):
    texto = diagramas(texto)
    texto = re.sub(r"!\[[^\]]*\]\((?!diagrama)[^)]*\)", "", texto)
    texto = re.sub(r"(?<!!)\[([^\]]+)\]\([^)]*\)", r"\1", texto).replace("\u2014", "-")
    salida, cerca, saltar, nivel_saltado, primero = [], False, False, 0, True
    for linea in texto.split("\n"):
        if linea.startswith("```"):
            cerca = not cerca
        if not cerca and linea.startswith("#"):
            nivel = len(linea) - len(linea.lstrip("#"))
            if primero:
                salida.append("# " + titulo); primero = False; continue
            if saltar and nivel <= nivel_saltado:
                saltar = False
            if any(o in linea for o in OMITIR):
                saltar, nivel_saltado = True, nivel
            linea = "#" + linea
        if not saltar:
            salida.append(linea)
    return "\n" + "\n".join(salida) + "\n"

base = Path(sys.argv[1])
partes = [Path(sys.argv[2]).read_text(encoding="utf-8")]
partes += [seccion((base / f).read_text(encoding="utf-8"), t) for f, t in SECCIONES]
sys.stdout.write("".join(partes))
for i, codigo in enumerate(DIAGRAMAS, 1):
    (Path(sys.argv[3]) / f"diagrama{i}.mmd").write_text(codigo, encoding="utf-8")
