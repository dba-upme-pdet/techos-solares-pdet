"""Fixtures sintéticos y HTTP local: nunca afirman cobertura oficial."""
import csv
import gzip
import importlib.util
import io
import os
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock as Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
spec = importlib.util.spec_from_file_location('download_google', ROOT/'scripts/03_download_google_buildings.py')
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
from google_buildings_adapter import google_features, google_attributes, REQUIRED_COLUMNS
from entrega3_contracts import download_manifest_problems
from shapely.geometry import box, mapping


def tile(pid, geom):
    return {'type':'Feature','properties':{'tile_id':pid,'tile_url':g.PREFIX+pid+'_buildings.csv.gz','size_mb':1},'geometry':mapping(geom)}


class GoogleDownloadTests(unittest.TestCase):
    def test_selection_and_gap(self):
        parts = [tile('a',box(-76,3,-75,4)),tile('b',box(-75,3,-74,4)),tile('c',box(0,0,1,1))]
        mun = [{'code':'synthetic','geometry':mapping(box(-75.5,3.1,-74.5,3.9))}]
        chosen, gaps = g.select_tiles(parts,mun)
        self.assertEqual([p['properties']['tile_id'] for p in chosen],['a','b']); self.assertEqual(gaps,[])
        self.assertEqual(g.select_tiles(parts[:1],mun)[1],['synthetic'])

    def test_index_invalid(self):
        good=tile('a',box(-76,3,-75,4))
        self.assertEqual(len(g.index_features({'type':'FeatureCollection','features':[good]})),1)
        for features in ([good,good], [{**good,'properties':{**good['properties'],'tile_url':'https://invalid/'}}]):
            with self.assertRaises(ValueError):g.index_features({'type':'FeatureCollection','features':features})

    def test_download_repeat_and_corruption(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'file.gz';session=Mock();response=session.get.return_value.__enter__.return_value
            response.headers={'Content-Length':'3'};response.iter_content.return_value=iter([b'abc'])
            first=g.download('https://fixture.invalid',p,session=session)
            self.assertEqual(first['bytes'],3)
            result=g.download('https://fixture.invalid',p,first,session=session)
            self.assertTrue(result['reused']); self.assertEqual(session.get.call_count,1)
            p.write_bytes(b'bad');response.iter_content.return_value=iter([b'abc'])
            g.download('https://fixture.invalid',p,first,session=session)
            self.assertEqual(p.read_bytes(),b'abc'); self.assertEqual(session.get.call_count,2)

    def test_failed_transfer_preserves_old_file(self):
        for headers in ({'Content-Length':'4'},{'Content-Length':'3','Content-MD5':'wrong'}):
            with tempfile.TemporaryDirectory() as d:
                p=Path(d)/'file';p.write_bytes(b'old');session=Mock();r=session.get.return_value.__enter__.return_value
                r.headers=headers;r.iter_content.return_value=iter([b'abc'])
                with self.assertRaises(ValueError):g.download('https://fixture.invalid',p,session=session)
                self.assertEqual(p.read_bytes(),b'old');self.assertFalse(p.with_name('file.part').exists())

    def test_adapter_inspection_no_confidence_filter(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'test.csv.gz'
            with gzip.open(p,'wt',newline='') as f:
                w=csv.DictWriter(f,fieldnames=sorted(REQUIRED_COLUMNS));w.writeheader()
                w.writerow({'latitude':3.5,'longitude':-75.5,'area_in_meters':123,'confidence':0.65,'full_plus_code':'SYNTHETIC','geometry':box(-75.6,3.4,-75.4,3.6).wkt})
            rows=list(google_features(p));self.assertEqual(len(rows),1)
            attrs, notes=google_attributes(rows[0][1]['properties']);self.assertEqual(attrs['confidence'],0.65);self.assertEqual(attrs['area_src_m2'],123)
            self.assertIsNone(attrs['height_m']); self.assertEqual(notes,[])
            self.assertTrue(g.inspect_file(p)['ok'])
            from shapely.geometry import MultiPolygon
            with gzip.open(p,'at',newline='') as f:
                w=csv.DictWriter(f,fieldnames=sorted(REQUIRED_COLUMNS))
                w.writerow({'latitude':3.5,'longitude':-75.5,'area_in_meters':123,'confidence':0.65,'full_plus_code':'SYNTHETIC','geometry':MultiPolygon([box(-75.6,3.4,-75.5,3.5),box(-75.4,3.6,-75.3,3.7)]).wkt})
            self.assertEqual(list(google_features(p))[1][1]['geometry']['type'],'MultiPolygon')
            self.assertEqual(g.inspect_file(p)['geometry_types']['MultiPolygon'],1)
            with gzip.open(p,'at') as f:f.write('bad\n')
            self.assertEqual(g.inspect_file(p)['invalid_rows'],1)

    def test_missing_columns_and_bad_gzip(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'test.gz'
            with gzip.open(p,'wt') as f:f.write('geometry\nINVALID\n')
            with self.assertRaises(ValueError):list(google_features(p))
            p.write_bytes(b'not gzip')
            with self.assertRaises(OSError):g.inspect_file(p)

    @unittest.skipUnless(os.environ.get('DEREK_PREPARER_PATH'), 'requiere preparador upstream explícito')
    def test_derek_preparer_with_google_adapter(self):
        spec=importlib.util.spec_from_file_location('derek_preparer_test',os.environ['DEREK_PREPARER_PATH'])
        prep=importlib.util.module_from_spec(spec);spec.loader.exec_module(prep)
        prep.SOURCES['google']={'config_key':'google','features':google_features,'attributes':google_attributes}
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'synthetic.csv.gz'
            with gzip.open(p,'wt',newline='') as f:
                w=csv.DictWriter(f,fieldnames=sorted(REQUIRED_COLUMNS));w.writeheader()
                w.writerow({'latitude':3.5,'longitude':-75.5,'area_in_meters':123,'confidence':0.65,'full_plus_code':'SYNTHETIC','geometry':box(-75.5001,3.4999,-75.4999,3.5001).wkt})
            result=prep.prepare_partition({'source_key':'google','dataset_id':'google','partition_id':'synthetic','input_path':str(p),'out_dir':str(Path(d)/'out'),'batch_size':10,'precision':7,'sliver_ratio':0.01,'check_records':True})
            self.assertEqual(result['counts']['prepared'],1)
            with gzip.open(result['paths']['part'],'rt') as f:record=json.loads(next(f))
            self.assertEqual(record['dataset_id'],'google');self.assertEqual(record['confidence'],0.65)
            self.assertEqual(record['area_src_m2'],123);self.assertGreater(record['area_m2'],0)

    def test_manifest_contract(self):
        manifest={'status':'complete','claims_pdet_coverage':True,'source':{'dataset_id':'google'},
          'datasets_document':dict(_id='google',name='synthetic',version='v3',license='CC-BY-4.0',url='https://fixture.invalid',accessed_at='2026-11-16'),
          'partitions':[{'partition_id':'a','status':'ok','local_path':'synthetic','download':{'sha256':'a'*64}}]}
        self.assertEqual(download_manifest_problems(manifest,'google'),[])
        manifest.update(status='partial',claims_pdet_coverage=False)
        self.assertEqual(len(download_manifest_problems(manifest,'google')),2)


if __name__=='__main__': unittest.main()
