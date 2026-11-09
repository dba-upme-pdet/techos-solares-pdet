# Entrega 2: filtrado y validación de municipios PDET

Responsable: Samuel Emperador. Script: `scripts/01_validate_mgn.py`.

El script cruza la capa municipal del MGN 2025 con la lista oficial de 170 municipios PDET y revisa códigos DIVIPOLA, duplicados, municipios faltantes y geometrías inválidas. No modifica la capa ni repara geometrías; solo reporta. La reparación (`make_valid`) y la conversión a GeoJSON son de `02_prepare_municipalities.py`.

## Comandos

```bash
python scripts/01_download_mgn.py      # Derek: deja la capa y el manifiesto
python scripts/01_validate_mgn.py --self-check
python scripts/01_validate_mgn.py
```

`--self-check` usa figuras sintéticas (no lee el MGN) y termina `FIXTURE self-check validación: 19/19`.

Códigos de salida: 0 si todas las verificaciones bloqueantes pasan, 1 si alguna falla y 2 si no hay una capa nacional verificada (sin manifiesto, manifiesto en `blocked`, capa ausente o con SHA256 distinto al del manifiesto).

## Entradas y salidas

| Pieza | Rol | Condición |
| --- | --- | --- |
| `outputs/mgn_download_manifest.json` | entrada (Derek) | `status = complete`, `claims_national_download = true`, `fixture` distinto de `true` |
| capa en `extracted_layer` del manifiesto | entrada (Derek) | GeoPackage con `MPIO_CDPMP`, `MPIO_CNMBR`, `MPIO_NAREA`, `DPTO_CCDGO`; SHA256 igual al del manifiesto |
| `resources/MunicipiosPDET.xlsx`, hoja `Hoja1` | entrada (curso) | columnas de `PDET_COLUMNS` en `entrega2_contracts.py` |
| `outputs/mgn_validation_report.json` | salida | contrato `entrega2-mgn-v1`, `role = validation-report`, `status` `valid`, `invalid` o `blocked_no_layer` |
| `outputs/mgn_validation_summary.md` | salida | tabla de verificaciones lista para el informe |
| `outputs/pdet_mgn_crosswalk.csv` | salida | una fila por municipio PDET: código, subregión, departamento en Excel y MGN, nombres, tipo de diferencia de nombre, tipo de geometría, problema de geometría y `area_km2_mgn` |

El cruce usa la misma regla que el resto del repositorio: `zfill` a 5 dígitos sobre `Código DANE Municipio` (`5031` → `05031`) y comparación por código, nunca por nombre. Las constantes (`REQUIRED_MGN_FIELDS`, `PDET_COLUMNS`, ventana de Colombia) y los utilitarios (`zfill_digits`, `normalize_label`, `crs_matches`) vienen de `entrega2_contracts.py`, así que el script valida exactamente lo que José prepara y Miguel carga.

José y Miguel pueden leer `status` de `mgn_validation_report.json` antes de preparar o cargar. Un valor distinto de `valid` significa que la capa o la lista no cumplen el contrato.

## Verificaciones

| # | Verificación | Bloquea |
| --- | --- | --- |
| 1 | campos obligatorios del MGN presentes | sí |
| 2 | capa nacional con `expected_feature_count` (1122) registros | sí |
| 3 | CRS igual a `sources.mgn.source_crs` (EPSG:4686) | sí |
| 4 | `MPIO_CDPMP` es un código de 5 dígitos | sí |
| 5 | los dos primeros dígitos de `MPIO_CDPMP` = `DPTO_CCDGO` | sí |
| 6 | los tres últimos dígitos de `MPIO_CDPMP` = `MPIO_CCDGO` | sí |
| 7 | sin códigos repetidos en el MGN | sí |
| 8 | `MPIO_NAREA` numérica y positiva | sí |
| 9 | geometrías del MGN no nulas, no vacías, poligonales y válidas (`is_valid`, con el motivo de `explain_validity`) | no: fuera de los PDET solo se reporta |
| 10 | todos los vértices dentro de la ventana lon/lat de Colombia (detecta ejes invertidos) | sí |
| 11 | lista PDET con 170 filas | sí |
| 12 | códigos PDET numéricos | sí |
| 13 | sin códigos repetidos en la lista PDET | sí |
| 14 | 16 subregiones | sí |
| 15 | prefijo del código PDET = `Código DANE Departamento` del Excel | sí |
| 16 | todos los municipios PDET existen en el MGN (faltantes) | sí |
| 17 | departamento del Excel = `DPTO_CCDGO` del MGN | sí |
| 18 | geometrías de los 170 PDET válidas | sí |
| 19 | nombres iguales entre Excel y MGN | no: informativo, separa diferencias de solo tildes |
| 20 | 170 municipios cruzados sin duplicados | sí |

El self-check prueba cada falla con un caso sintético: municipio ausente, código repetido en cada fuente, prefijo de departamento distinto, código no numérico, polígono autointersecado (en un PDET falla, fuera de los PDET solo avisa), punto en vez de polígono, ejes lat/lon invertidos, CRS EPSG:3857, capa incompleta, campo faltante y manifiesto ausente o bloqueado.

## Evidencia de la capa real

Corrida el 2026-11-08 con Python 3.13.12, GeoPandas 1.2.0, pyproj 3.8.0, pandas 3.1.1 y shapely 2.2.0, sobre la capa que produce `01_download_mgn.py` a partir de las seis respuestas WFS del recibo.

Resultado: **valid**, 19 de 20 verificaciones en OK y 1 aviso informativo. Salida 0.

- 1122 municipios en el MGN, todos `MultiPolygon`, en EPSG:4686.
- 0 códigos con formato inválido, 0 prefijos o sufijos inconsistentes, 0 duplicados en el MGN y 0 en la lista PDET.
- 170 de 170 municipios PDET cruzados, 0 faltantes, 0 departamentos distintos, 16 subregiones.
- 0 geometrías inválidas, nulas o vacías, tanto en los 1122 como en los 170 PDET. Ninguna fuera de la ventana de Colombia.
- Área MGN total de los 170 PDET: 389 182,0 km².
- 15 nombres distintos entre Excel y MGN: 9 solo por tildes (por ejemplo `27099` BOJAYA / BOJAYÁ) y 6 por forma oficial (`19548` PIENDAMÓ / PIENDAMÓ - TUNÍA, `50711` VISTA HERMOSA / VISTAHERMOSA, `70523` SAN ANTONIO DE PALMITO / PALMITO, `70823` TOLÚ VIEJO / SAN JOSÉ DE TOLUVIEJO, `19418` LÓPEZ / LÓPEZ DE MICAY, `86573` LEGUÍZAMO / PUERTO LEGUÍZAMO). Ninguno afecta el cruce. La cifra coincide con `name_mismatches = 15` del reporte de preparación.

La tabla completa está en `outputs/mgn_validation_summary.md` y el cruce fila por fila en `outputs/pdet_mgn_crosswalk.csv`.

## Observaciones para el equipo

- El SHA256 del GeoPackage cambia entre máquinas aunque el contenido sea el mismo, porque GeoPackage (SQLite) guarda la fecha de escritura. Aquí la capa quedó en `1dbe68b2…` y el manifiesto del repositorio dice `fe6bdebf…`. El GeoJSONL de `02_prepare_municipalities.py` sí sale idéntico (`612e2544…`). Por eso este script compara la capa contra el manifiesto de la misma corrida: hay que correr `01_download_mgn.py` antes en la misma máquina.
- Cada respuesta del WFS trae un atributo `timeStamp` con la hora del servidor en la cabecera `wfs:FeatureCollection`. Una descarga nueva tiene los mismos bytes de tamaño, pero otro SHA256, y `01_download_mgn.py` la rechaza contra el recibo. Al restituir el `timeStamp` original (`2026-11-08T20:23:33Z` para `page_0000.gml`) el hash coincide con el recibo, así que el contenido servido no cambió. Se sugiere que el recibo compare el hash con `timeStamp` normalizado.
