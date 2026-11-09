# Validación del MGN contra la lista PDET

Generado por `scripts/01_validate_mgn.py` el 2026-11-08T19:36:00-05:00.

- Estado: **valid** (19/20 verificaciones).
- Capa: `data/raw/mgn2025/wfs/municipio.gpkg` (SHA256 `1dbe68b21677b643…`).
- Municipios en el MGN: 1122. Municipios PDET cruzados: 170 de 170.
- Área MGN total de los PDET: 389,182.0 km².

| Verificación | Resultado | Detalle |
| --- | --- | --- |
| campos obligatorios del MGN | OK | presentes |
| capa nacional con 1122 municipios | OK | 1122 registros |
| CRS EPSG:4686 | OK | EPSG:4686 |
| MPIO_CDPMP es DIVIPOLA de 5 dígitos | OK | ninguno |
| prefijo de MPIO_CDPMP = DPTO_CCDGO | OK | ninguno |
| sufijo de MPIO_CDPMP = MPIO_CCDGO | OK | ninguno |
| sin códigos repetidos en el MGN | OK | ninguno |
| MPIO_NAREA positiva | OK | ninguno |
| geometrías válidas en el MGN | OK | ninguno |
| geometrías dentro de la ventana de Colombia (lon/lat) | OK | ninguno |
| lista PDET con 170 filas | OK | 170 filas |
| códigos PDET numéricos | OK | ninguno |
| sin códigos repetidos en la lista PDET | OK | ninguno |
| 16 subregiones PDET | OK | 16 subregiones |
| prefijo de código PDET = departamento del Excel | OK | ninguno |
| todos los municipios PDET están en el MGN | OK | ninguno |
| departamento del Excel = DPTO_CCDGO del MGN | OK | ninguno |
| geometrías PDET válidas | OK | ninguno |
| nombres Excel = MGN (informativo; el cruce es por código) | AVISO | 15 distintos (9 solo por tildes) |
| cruce completo de 170 municipios PDET | OK | 170 cruzados |

## Nombres distintos entre el Excel y el MGN

| Código | Excel | MGN | Tipo |
| --- | --- | --- | --- |
| 19548 | PIENDAMÓ | PIENDAMÓ - TUNÍA | distinto |
| 19821 | TORIBIO | TORIBÍO | solo_tildes |
| 27099 | BOJAYA | BOJAYÁ | solo_tildes |
| 27150 | CARMEN DEL DARIEN | CARMEN DEL DARIÉN | solo_tildes |
| 18256 | EL PAUJIL | EL PAUJÍL | solo_tildes |
| 50711 | VISTA HERMOSA | VISTAHERMOSA | distinto |
| 70204 | COLOSO | COLOSÓ | solo_tildes |
| 70523 | SAN ANTONIO DE PALMITO | PALMITO | distinto |
| 70823 | TOLÚ VIEJO | SAN JOSÉ DE TOLUVIEJO | distinto |
| 19418 | LÓPEZ | LÓPEZ DE MICAY | distinto |
| 52427 | MAGÜI | MAGÜÍ | solo_tildes |
| 52835 | SAN ANDRES DE TUMACO | SAN ANDRÉS DE TUMACO | solo_tildes |
| 86573 | LEGUÍZAMO | PUERTO LEGUÍZAMO | distinto |
| 23682 | SAN JOSE DE URE | SAN JOSÉ DE URÉ | solo_tildes |
| 05665 | SAN PEDRO DE URABA | SAN PEDRO DE URABÁ | solo_tildes |
