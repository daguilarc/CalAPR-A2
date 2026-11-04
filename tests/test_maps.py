"""Diego's annual and reported unrestricted map selections must retain their counts."""
from copy import deepcopy
import itertools
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import numpy as np
import pandas as pd
from maps import build_maps as m


def fixture():
    records = []
    for year, city, factor in [(2018, 'Alpha', 1), (2024, 'Beta', 3), (2024, 'Test County', 5), (2017, 'Alpha', 7)]:
        row = dict(YEAR=year, JURIS_NAME=city, CNTY_NAME='Test', UNIT_CAT='5+', TENURE='OWNER', DR_TYPE='DB',
                   DEM_DES_UNITS=2, NO_ENTITLEMENTS=30*factor, NO_BUILDING_PERMITS=20*factor, NO_OTHER_FORMS_OF_READINESS=10*factor,
                   EXTR_LOW_INCOME_UNITS=999)
        for stage in m.STAGE_METADATA:
            prefix = stage['prefix']
            for tier, number in [('VLOW', 1), ('LOW', 2), ('MOD', 4)]:
                row[m.income_col_names(prefix, tier, 'ndr')[0]] = number*factor
                row[m.income_col_names(prefix, tier, 'dr')[0]] = 10*number*factor
            row[m.income_col_names(prefix, 'ABOVE_MOD')[0]] = 8*factor
        records.append(row)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)/'fixture.csv'; pd.DataFrame(records).to_csv(path,index=False)
        rows, stats = m.prepare_rows(path)
    features=[]
    for kind,name in [('county_whole',''),('county_residual',''),('city','Alpha'),('city','Beta')]:
        features.append(dict(type='Feature',geometry={'type':'Polygon','coordinates':[[[0,0],[1,0],[1,1],[0,0]]]},properties=dict(feature_id=str(len(features)),geo_type=kind,city_name=name,county_name='Test',county_fips='001',population=100)))
    geometry,data=m.build_cube(rows,dict(type='FeatureCollection',features=features))
    return rows,stats,geometry,data


class MapSelections(unittest.TestCase):
    def test_reported_unrestricted_and_existing_net(self):
        rows,stats,_,data=fixture()
        self.assertEqual(stats['rows_in_year_range'],3)
        for stage in m.STAGE_METADATA:
            key=stage['key']
            np.testing.assert_equal(rows[key+'_nonrestricted'].to_numpy(),[15,45,75])
            np.testing.assert_equal(rows[key+'_low_dr'].to_numpy(),[20,60,100])
        self.assertEqual(rows['ENT_net'].tolist(),[30,90,150])
        self.assertEqual(rows['BP_net'].tolist(),[18,58,98])
        self.assertEqual(rows['CO_net'].tolist(),[10,30,50])
        # An unrestricted-only group must survive the cube's activity filter.
        only=rows.iloc[:1].copy(); only[m.PRIMITIVES]=0; only['CO_nonrestricted']=11
        _,active=m.build_cube(only,{'features':fixture()[2]['features']})
        self.assertEqual(m.compose_counts(active,{'affordability':'none'})[0],11)

    def test_annual_additivity_county_identity_and_named_schema(self):
        _,_,_,data=fixture()
        for housing,stage,tenure,program,income in itertools.product(*[[c['key'] for c in a['choices']] for a in data['axes'] if a['key'] in ('housing','stage','tenure','program','affordability')]):
            # Axis order is housing,stage,tenure,program,affordability.
            selection=dict(zip(('housing','stage','tenure','program','affordability'),(housing,stage,tenure,program,income)))
            all_years=m.compose_counts(data,selection)
            annual=sum((m.compose_counts(data,{**selection,'year':str(y)}) for y in m.BUCKETS['year']))
            np.testing.assert_equal(all_years,annual)
        atomic=np.asarray(data['partitions']); dims=5
        for buckets in set(map(tuple,atomic[:,1:dims])):
            selected=atomic[(atomic[:,1:dims]==buckets).all(axis=1)]
            by_feature={int(row[0]):row[dims:] for row in selected}
            np.testing.assert_equal(by_feature.get(0,np.zeros(15)),sum((by_feature.get(i,np.zeros(15)) for i in (1,2,3))))
        reordered=deepcopy(data); order=list(reversed(range(len(data['row_schema']))))
        reordered['row_schema']=[data['row_schema'][i] for i in order]
        reordered['partitions']=[[r[i] for i in order] for r in data['partitions']]
        np.testing.assert_equal(m.compose_counts(data,{'affordability':'none','year':'2024'}),m.compose_counts(reordered,{'affordability':'none','year':'2024'}))

    def test_html_runtime_matches_python_and_rejects_old_schema(self):
        _,_,geometry,data=fixture()
        script=Path(__file__).resolve().parents[1].joinpath('docs/index.html').read_text().split('<script>')[1].split('</script>')[0]
        # Execute the shipped load handler, change listeners and composer with DOM/Plotly stand-ins.
        harness=r'''
const fs=require('fs'),vm=require('vm');const input=JSON.parse(fs.readFileSync(0,'utf8'));
const elements={};function element(){return {children:[],value:'',textContent:'',append(x){this.children.push(x)},addEventListener(k,f){this[k]=f},setAttribute(){}}}
for(const id of ['status','map-chart','map-controls'])elements[id]=element();
let loader;global.window={innerWidth:1200,addEventListener(k,f){loader=f}};global.document={getElementById:id=>elements[id],createElement:()=>element()};
global.fetch=async url=>({ok:true,json:async()=>url.endsWith('map_data.json')?input.data:input.geometry});
let captured;global.Plotly={react(chart,traces,layout){captured=traces[0];chart.layout=layout;return {then(){return {catch(){}}}}}};window.Plotly=Plotly;
vm.runInThisContext(input.script);(async()=>{await loader();if(input.data.schema_version===2){console.log(JSON.stringify({status:elements.status.textContent}));return;}
const selects=Object.fromEntries(elements['map-controls'].children.map((l,i)=>[input.data.axes[i].key,l.children[0]]));let results=[];
for(const selection of input.selections){for(const axis of input.data.axes)selects[axis.key].value=selection[axis.key]??axis.default;selects.year.change();results.push(captured.customdata.map(x=>x[0]));}console.log(JSON.stringify({results,defaults:input.data.axes.map(a=>[a.key,a.default])}));})();
'''
        selections=[dict(stage=s['key'],affordability=c['key'],year=y,geography='whole_counties') for s in m.STAGE_METADATA for c in data['axes'][5]['choices'] for y in ['all',*map(str,m.BUCKETS['year'])]]
        for reorder in (False,True):
            payload=deepcopy(data)
            if reorder:
                order=list(reversed(range(len(data['row_schema']))));payload['row_schema']=[data['row_schema'][i] for i in order];payload['partitions']=[[r[i] for i in order] for r in data['partitions']]
            result=json.loads(subprocess.check_output(['node','-e',harness],input=json.dumps(dict(data=payload,geometry=geometry,script=script,selections=selections)).encode()))
            for selection,actual in zip(selections,result['results']):self.assertEqual(actual,[m.compose_counts(payload,selection)[0]])
        data['schema_version']=2
        result=json.loads(subprocess.check_output(['node','-e',harness],input=json.dumps(dict(data=data,geometry=geometry,script=script,selections=[])).encode()))
        self.assertIn('schema do not match',result['status'])

if __name__=='__main__':unittest.main()
