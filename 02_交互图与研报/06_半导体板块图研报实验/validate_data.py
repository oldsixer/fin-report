"""Check raw-pointer round trips, dependencies, coverage and calculations."""
from pipeline import ROOT,save,credentials,SAMPLES
from prepare import read
import json,hashlib,statistics,math

sources=read('03_规范化证据/sources.json');rr=read('03_规范化证据/records.json');ds=read('03_规范化证据/derived.json')
raw={s['source_id']:json.loads((ROOT/s['raw_path']).read_bytes()) for s in sources}
for r in rr:
    actual=raw[r['source_id']]
    for part in r['json_pointer'].strip('/').split('/'):actual=actual[int(part)] if isinstance(actual,list) else actual[part]
    assert actual==r['data'],r['record_id']
byid={r['record_id']:r for r in rr}
for d in ds:
    assert all(i in byid for i in d['input_record_ids'])
    assert set(d['source_ids'])=={byid[i]['source_id'] for i in d['input_record_ids']}
def equal(a,b):assert math.isclose(a,b,abs_tol=1.1e-6),[a,b]
for d in ds[:8]:
    inputs=[byid[i] for i in d['input_record_ids']]
    inc=next(r['data'] for r in inputs if r['source_name'].startswith('income_') and r['data']['fiscal_year']==2026)
    prev=next(r['data'] for r in inputs if r['source_name'].startswith('income_') and r['data']['fiscal_year']==2025)
    cash=next(r['data'] for r in inputs if r['source_name'].startswith('cash_'))
    bal=next(r['data'] for r in inputs if r['source_name'].startswith('balance_'))
    m=d['metrics'];equal(m['revenue_cny_100m'],inc['operating_income']/100000000)
    equal(m['revenue_yoy_pct'],100*(inc['operating_income']-prev['operating_income'])/prev['operating_income'])
    equal(m['parent_net_profit_cny_100m'],inc['parent_holder_net_profit']/100000000)
    equal(m['operating_cash_cny_100m'],cash['act_cash_flow_net']/100000000)
    equal(m['ocf_less_capex_proxy_cny_100m'],(cash['act_cash_flow_net']-cash['pay_fixed_assets_etc_cash'])/100000000)
    assert abs(bal['assets_total']-bal['total_debt']-bal['holder_equity_total'])<max(1,bal['assets_total']*1e-6)
for d in ds[8:12]:
    rows=sorted((byid[i]['data'] for i in d['input_record_ids']),key=lambda r:r['date_ms']);p=[r['close_price'] for r in rows]
    equal(d['metrics']['price_return_pct'],100*(p[-1]-p[0])/p[0]);equal(d['metrics']['max_drawdown_pct'],min((p[j]-max(p[:j+1]))/max(p[:j+1]) for j in range(len(p)))*100)
for d in ds[15:18]:
    m=d['metrics'];assert m['up']+m['down']+m['flat']==m['valid_price_change_count'];assert m['positive_pe_count']+m['nonpositive_pe_count']+m['missing_pe_count']==m['valuation_returned']
    equal(m['up_ratio_valid_pct'],100*m['up']/m['valid_price_change_count'])
assert any(byid[i]['data'].get('fiscal_year')==2025 for i in ds[18]['input_record_ids'])
key=credentials()[1].encode();scanned=0
for folder in ['02_原始数据','03_规范化证据','04_知识图','05_隔离输入与运行记录','06_研报与对照']:
    for path in (ROOT/folder).rglob('*'):
        if not path.is_file():continue
        b=path.read_bytes();scanned+=1;assert key not in b,'credential occurrence'
        if path.suffix not in ['.png'] and path.name not in ['report_validation.json','方法与结果审计.md','方法与结果审计.html']:
            for excluded in ['长江存储','YMTC','Xtacking','致态']:assert excluded.encode() not in b,'excluded theme: '+str(path)
save('06_研报与对照/data_validation.json',{'raw_pointer_roundtrips':len(rr),'all_passed':True,'derived_dependency_groups':len(ds),'financial_recalculations':40,'index_recalculations':8,'balance_sheet_identities':8,'cross_section_denominators':3,'credential_occurrences':0,'files_scanned':scanned,'topic_check':'本轮数据、图、输入和报告无旧主题内容；不扫描旧实验'})
print('data, dependency, scope and credential checks passed')
