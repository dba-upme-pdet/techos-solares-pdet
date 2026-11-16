"""Google v3 CSV.gz/WKT -> interfaz de lectores de 03_prepare_buildings.py.

No filtra, repara ni asigna municipio. Conserva MultiPolygon para que la
preparación reporte explícitamente los tipos que su esquema no admite.
"""
import csv
import gzip
import math

from shapely import wkt
from shapely.geometry import mapping

REQUIRED_COLUMNS = {'latitude', 'longitude', 'area_in_meters', 'confidence', 'geometry', 'full_plus_code'}


def google_features(path):
    """Itera (número de registro CSV, Feature|None), sin cargar el archivo completo."""
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as handle:
        reader = csv.DictReader(handle)
        if not REQUIRED_COLUMNS <= set(reader.fieldnames or []):
            raise ValueError('CSV Google sin las seis columnas requeridas')
        for number, row in enumerate(reader, 1):
            try:
                props = {k: float(row[k]) for k in ['latitude', 'longitude', 'area_in_meters', 'confidence']}
                if not all(math.isfinite(v) for v in props.values()):
                    raise ValueError('atributo no finito')
                props['full_plus_code'] = row['full_plus_code']
                yield number, {'type': 'Feature', 'geometry': mapping(wkt.loads(row['geometry'])), 'properties': props}
            except (ValueError, TypeError, KeyError):
                yield number, None
            except Exception as exc:
                from shapely.errors import GEOSException
                if not isinstance(exc, GEOSException):
                    raise
                yield number, None


def google_attributes(props):
    from entrega3_contracts import clean_unit_interval
    confidence, note = clean_unit_interval(props.get('confidence'), 'confidence_unknown', 'confidence_out_of_range')
    return {'area_src_m2': props.get('area_in_meters'), 'confidence': confidence, 'height_m': None}, ([note] if note else [])
