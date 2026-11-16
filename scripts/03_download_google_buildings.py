"""Adquiere Google Open Buildings v3: índice oficial, plan PDET y CSV.gz intactos.

0: descarga completa verificada; 1: fallo, plan o cobertura pendiente.
--plan-only no descarga polígonos. --probe-tile descarga una muestra explícita,
siempre parcial, incluso cuando faltan los municipios; nunca acredita PDET.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import math
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests
from shapely.geometry import shape
from shapely.ops import unary_union

from entrega2_contracts import ContractError, load_config, sha256_file, write_json
from entrega3_contracts import download_manifest_problems, load_pdet_layer
from google_buildings_adapter import google_features

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'https://storage.googleapis.com/open-buildings-data/v3/polygons_s2_level_4_gzip/'


def download(url, path, previous=None, session=None):
    """SHA256 + bytes + MD5 servidor si se publica. .part nunca se reutiliza."""
    session = session or requests.Session()
    path.parent.mkdir(parents=True, exist_ok=True)
    if previous and path.is_file() and previous.get('bytes') == path.stat().st_size and previous.get('sha256') == sha256_file(path):
        return {**previous, 'reused': True}
    tmp = path.with_name(path.name + '.part')
    digest, md5, size = hashlib.sha256(), hashlib.md5(), 0
    try:
        with session.get(url, stream=True, timeout=(15, 120), headers={'Accept-Encoding': 'identity'}) as response:
            response.raise_for_status()
            with tmp.open('wb') as out:
                for chunk in response.iter_content(1024 * 1024):
                    out.write(chunk); digest.update(chunk); md5.update(chunk); size += len(chunk)
            expected = response.headers.get('Content-Length')
            if expected and size != int(expected):
                raise ValueError('tamaño recibido distinto de Content-Length')
            hashes = dict(v.strip().split('=', 1) for v in response.headers.get('x-goog-hash', '').split(',') if '=' in v)
            expected_md5 = response.headers.get('Content-MD5') or hashes.get('md5')
            if expected_md5 and base64.b64encode(md5.digest()).decode() != expected_md5:
                raise ValueError('MD5 recibido distinto del publicado por el servidor')
            result = {'bytes': size, 'sha256': digest.hexdigest(), 'md5': base64.b64encode(md5.digest()).decode(),
                      'server_md5': expected_md5, 'etag': response.headers.get('ETag'),
                      'last_modified': response.headers.get('Last-Modified'), 'reused': False}
        tmp.replace(path)
        return result
    finally:
        if tmp.exists(): tmp.unlink()


def index_features(payload):
    if payload.get('type') != 'FeatureCollection' or not payload.get('features'):
        raise ValueError('índice sin FeatureCollection')
    seen = set()
    for f in payload['features']:
        props = f['properties']; pid = str(props['tile_id'])
        if pid in seen or not pid or props['tile_url'] != PREFIX + pid + '_buildings.csv.gz':
            raise ValueError('índice con identificador duplicado o URL inesperada')
        seen.add(pid)
        geom = shape(f['geometry'])
        if geom.is_empty or not geom.is_valid or geom.geom_type not in ('Polygon', 'MultiPolygon'):
            raise ValueError('geometría del índice inválida')
        if not math.isfinite(float(props['size_mb'])) or float(props['size_mb']) < 0:
            raise ValueError('tamaño del índice inválido')
    return payload['features']


def select_tiles(features, municipalities):
    geoms = [shape(m['geometry']) for m in municipalities]
    if not geoms or any(not g.is_valid or g.is_empty for g in geoms):
        raise ValueError('límites municipales ausentes o inválidos')
    selected = [f for f in features if any(shape(f['geometry']).intersects(g) for g in geoms)]
    union = unary_union([shape(f['geometry']) for f in selected])
    uncovered = [m['code'] for m,g in zip(municipalities,geoms) if not union.buffer(1e-8).covers(g)]
    return selected, uncovered


def inspect_file(path):
    """Lee el gzip entero en bloques de 10.000 filas; valida WKT vectorialmente."""
    import csv
    import gzip
    import numpy as np
    import shapely
    from google_buildings_adapter import REQUIRED_COLUMNS
    count = invalid = 0; types = Counter()
    keys = ['area_in_meters', 'confidence', 'longitude', 'latitude']
    ranges = {k: [None, None] for k in keys}
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as handle:
        reader = csv.DictReader(handle)
        if not REQUIRED_COLUMNS <= set(reader.fieldnames or []):
            raise ValueError('CSV Google sin las seis columnas requeridas')
        from itertools import islice
        while rows := list(islice(reader, 10000)):
            count += len(rows)
            geoms = shapely.from_wkt([r.get('geometry') or '' for r in rows], on_invalid='ignore')
            values = []
            for r in rows:
                try: values.append([float(r[k]) for k in keys])
                except (ValueError, TypeError, KeyError): values.append([float('nan')]*4)
            nums = np.array(values)
            bounds = shapely.bounds(geoms)
            ids = shapely.get_type_id(geoms)
            valid = (shapely.is_valid(geoms) & ~shapely.is_empty(geoms) & np.isin(ids,[3,6])
                     & np.isfinite(bounds).all(axis=1) & np.isfinite(nums).all(axis=1)
                     & (bounds[:,0]>=-180) & (bounds[:,2]<=180) & (bounds[:,1]>=-90) & (bounds[:,3]<=90)
                     & (nums[:,0]>0) & (nums[:,1]>=0) & (nums[:,1]<=1)
                     & (nums[:,2]>=-180) & (nums[:,2]<=180) & (nums[:,3]>=-90) & (nums[:,3]<=90))
            invalid += int((~valid).sum())
            for ident,n in Counter(ids.tolist()).items():
                types[{3:'Polygon',6:'MultiPolygon',-1:'unparseable'}.get(ident,str(ident))] += n
            for i,key in enumerate(keys):
                finite = nums[:,i][np.isfinite(nums[:,i])]
                if len(finite):
                    low,high = float(finite.min()),float(finite.max()); old = ranges[key]
                    old[0] = low if old[0] is None else min(low,old[0]);old[1] = high if old[1] is None else max(high,old[1])
    return {'rows':count,'invalid_rows':invalid,'geometry_types':dict(types),'ranges':ranges,
            'read_entire_gzip':True,'confidence_filter_applied':False,'batch_rows':10000,'ok':count>0 and invalid==0}


def run(root, args):
    cfg = load_config(root); conf = cfg['sources']['google']; raw = root/cfg['paths']['raw_data']/conf['raw_dir']
    output = root/conf['manifest']
    if args.probe_tile: output = output.with_name('google_buildings_probe_manifest.json')
    elif args.plan_only: output = output.with_name('google_buildings_download_plan.json')
    now = datetime.now(timezone.utc).isoformat()
    previous = json.loads(output.read_text()) if output.exists() else {}
    report = {'contract': 'entrega3-buildings-v1', 'status': 'blocked', 'claims_pdet_coverage': False,
              'checked_at': now, 'source': {'dataset_id': 'google', 'version': conf['version'], 'url': conf['url'], 'crs': 'EPSG:4326', 'format': 'CSV.gz/WKT'},
              'datasets_document': {'_id': 'google', 'name': 'Google Open Buildings', 'version': conf['version'],
                                    'license': conf['license'], 'url': conf['url'], 'accessed_at': now},
              'partitions': [], 'selection': {'criterion': 'intersección de polígonos municipales con celdas del índice S2 nivel 4; sin filtro de confianza', 'probe_tile': args.probe_tile},
              'preparation_reader_registered': False}
    try:
        if conf['version'] != 'v3': raise ValueError('este lector está verificado para v3')
        raw.mkdir(parents=True, exist_ok=True)
        index_path = raw/'tiles.geojson'
        report['index'] = {'url': conf['index_url'], 'local_path': str(index_path.relative_to(root)),
                           'download': download(conf['index_url'], index_path)}
        features = index_features(json.loads(index_path.read_text()))
        report['index']['tile_count'] = len(features)
        try:
            municipalities, digest = load_pdet_layer(root, conf['pdet_input'], conf['pdet_input_report'], 170)
            # Compuerta de integridad más estricta: el reporte debe declarar hash y códigos.
            prep = json.loads((root/conf['pdet_input_report']).read_text())
            if prep.get('sha256') != digest or set(prep.get('ids', [])) != {m['code'] for m in municipalities} or len({m['code'] for m in municipalities}) != 170:
                raise ContractError('hash/códigos municipales inconsistentes con el reporte')
            from pandas import read_excel
            ref = cfg['sources']['pdet_list']
            from entrega2_contracts import zfill_digits
            official = {zfill_digits(v,5) for v in read_excel(root/ref['file'], sheet_name=ref['sheet'])[ref['code_column'] ]}
            if official != {m['code'] for m in municipalities}: raise ContractError('no son los 170 códigos oficiales PDET')
            selected, uncovered = select_tiles(features, municipalities)
            report['selection'].update(municipal_sha256=digest, municipalities=170, uncovered_municipalities=uncovered)
        except (ContractError, FileNotFoundError) as exc:
            report['selection']['blocked_reason'] = str(exc)
            if not args.probe_tile: raise
            selected, uncovered = [], ['not_verified']
        if args.probe_tile:
            selected = [f for f in features if str(f['properties']['tile_id']) == args.probe_tile]
            if not selected: raise ValueError('tile de muestra no existe en índice oficial')
        report['selection']['tile_ids'] = [str(f['properties']['tile_id']) for f in selected]
        report['selection']['estimated_compressed_bytes'] = sum(int(float(f['properties']['size_mb'])*1_000_000) for f in selected)
        free = shutil.disk_usage(raw).free; report['disk_free_bytes_before'] = free
        for f in selected:
            props = f['properties']; pid = str(props['tile_id'])
            report['partitions'].append({'partition_id': pid, 'url': props['tile_url'], 'local_path': str((raw/(pid+'_buildings.csv.gz')).relative_to(root)), 'estimated_bytes': int(float(props['size_mb'])*1_000_000), 'status': 'planned'})
        if args.plan_only:
            report['status'] = 'planned'
        else:
            if free < report['selection']['estimated_compressed_bytes']*1.1: raise OSError('espacio disponible insuficiente para el plan')
            for part in report['partitions']:
                old = next((p for p in previous.get('partitions',[]) if p.get('partition_id')==part['partition_id'] and p.get('url')==part['url'] and p.get('status') in ('ok','downloaded')),{})
                part['download'] = download(part['url'], root/part['local_path'], old.get('download'))
                part['status'] = 'downloaded'
                write_json(output, report)
                part['inspection'] = inspect_file(root/part['local_path'])
                part['status'] = 'ok' if part['inspection']['ok'] else 'invalid'
                write_json(output, report)  # progreso sin afirmar cobertura completa
            complete = bool(selected) and not args.probe_tile and not uncovered and all(p['status']=='ok' for p in report['partitions'])
            report['status'] = 'complete' if complete else 'partial'
            report['claims_pdet_coverage'] = complete
            report['coverage_meaning'] = 'se descargaron y leyeron todas las particiones que cubren los límites PDET; no garantiza edificios detectados en cada municipio ni ausencia de omisiones del modelo'
    except (requests.RequestException, OSError, EOFError, ValueError, KeyError, ContractError) as exc:
        report.update(status='blocked', claims_pdet_coverage=False, error=f'{type(exc).__name__}: {exc}')
    report['manifest_contract_problems'] = download_manifest_problems(report, 'google')
    write_json(output, report)
    print(f"[{report['status']}] {len(report['partitions'])} particiones; bytes verificados: {sum(p.get('download',{}).get('bytes',0) for p in report['partitions'])}")
    if report.get('error'): print(report['error'])
    return 0 if report['status']=='complete' and not report['manifest_contract_problems'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan-only', action='store_true')
    parser.add_argument('--probe-tile', help='muestra real explícita, nunca equivale a cobertura PDET')
    args = parser.parse_args()
    return run(ROOT, args)


if __name__ == '__main__': sys.exit(main())
