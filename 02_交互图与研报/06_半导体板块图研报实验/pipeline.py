"""Fresh, read-only sector data collection; never persist authentication headers."""
from pathlib import Path
import ast,datetime as dt,hashlib,json,time,urllib.request,urllib.parse,urllib.error,sys
ROOT=Path(__file__).resolve().parent
CONFIG=Path('/Users/nelson/Documents/ZSZQ/hithink_api_config.py')
SAMPLES=['603986.SH','688008.SH','688981.SH','002371.SZ','688012.SH','600584.SH','002156.SZ','688126.SH']
INDICES={'881121.TI':'半导体','884229.TI':'半导体设备','884091.TI':'半导体材料','000300.SH':'沪深300'}
def save(path,value):
    path=ROOT/path;path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2) if not isinstance(value,str) else value,encoding='utf-8')
def credentials():
    values={}
    for n in ast.parse(CONFIG.read_text()).body:
        if isinstance(n,ast.Assign):
            for target in n.targets:
                if isinstance(target,ast.Name):
                    try:values[target.id]=ast.literal_eval(n.value)
                    except (ValueError,TypeError):pass
    base=values['HITHINK_FINANCE_BASE_URL'].rstrip('/')
    u=urllib.parse.urlparse(base)
    if u.scheme!='https' or u.netloc!='fuyao.aicubes.cn':raise ValueError('Unexpected credential destination')
    return base,values['HITHINK_FINANCE_API_KEY']
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None
def fetch(name,path,params):
    output=ROOT/'02_原始数据'/f'{name}.json'
    if output.exists():return json.loads(output.read_text())
    base,key=credentials();url=base+path+'?'+urllib.parse.urlencode(params)
    record={'name':name,'url':url,'fetched_at':dt.datetime.now(dt.timezone.utc).isoformat()}
    try:
        req=urllib.request.Request(url,headers={'Accept':'application/json','X-api-key':key,'User-Agent':'FinAgent-SectorResearch/1.0'})
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=30) as response:raw=response.read();status=response.status
    except urllib.error.HTTPError as e:raw=e.read();status=e.code
    except Exception as e:
        record.update({'status':'network_error','error_type':type(e).__name__});save(output,record);print(name,record['status'],flush=True);return record
    if key.encode() in raw:raise RuntimeError('Response echoed credential; not persisted')
    output.parent.mkdir(parents=True,exist_ok=True);output.with_suffix('.body').write_bytes(raw)
    try:payload=json.loads(raw)
    except (json.JSONDecodeError,UnicodeDecodeError):payload={'unparsed_response':True}
    record.update({'http_status':status,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'payload':payload});save(output,record)
    print(name,status,'business',payload.get('code'),'items',len((payload.get('data') or {}).get('item',[])),flush=True)
    if status==429 or payload.get('code') in [2001,2003,4001]:raise RuntimeError('Stop on authentication/permission/rate limit')
    return record
def get(name,path,params):
    r=fetch(name,path,params)
    if r.get('status')=='network_error':
        time.sleep(.6);r=fetch(name+'_retry1',path,params)
    time.sleep(.35);return r
def items(r):return (r.get('payload',{}).get('data') or {}).get('item',[])
def collect():
    metadata=get('index_search','/api/meta/tickers/search',{'q':'半导体','asset_type':'a-share-index','limit':30})
    found={x['thscode']:x['name'] for x in items(metadata)}
    for code in list(INDICES)[:-1]:
        if found.get(code)!=INDICES[code]:raise RuntimeError('Index metadata mismatch: '+code)
    members={}
    for code in list(INDICES)[:-1]:members[code]=items(get('members_'+code,'/api/a-share-index/constituents/ths-stock-list',{'thscode':code}))
    universe=sorted({x['thscode'] for x in members['881121.TI']})
    if not set(SAMPLES)<=set(universe):raise RuntimeError('Preselected sample not in current main sector')
    save('00_方案与说明/采集范围.json',{'main_sector':'881121.TI','indices':INDICES,'full_constituent_count':len(universe),'full_constituents':universe,'financial_samples':SAMPLES,'selection':'预设观察样本，非随机；财务样本统计不外推全板块。'})
    for i in range(0,len(universe),50):
        params={'thscodes':','.join(universe[i:i+50])}
        get(f'prices_{i//50+1:02d}','/api/a-share/prices/snapshot',params)
        get(f'valuations_{i//50+1:02d}','/api/a-share/valuations/snapshot',params)
    get('index_snapshot','/api/a-share-index/prices/snapshot',{'thscodes':','.join(INDICES)})
    def ms(day):return int(dt.datetime.fromisoformat(day+'T00:00:00+08:00').timestamp()*1000)
    for code in INDICES:get('history_'+code,'/api/a-share-index/prices/historical',{'thscode':code,'interval':'1d','start':ms('2026-06-15'),'end':ms('2026-09-14')})
    for code in SAMPLES:
        for prefix,endpoint,limit in [('income','income-statements',6),('balance','balance-sheets',3),('cash','cash-flow-statements',6)]:
            get(prefix+'_'+code,'/api/a-share/financials/'+endpoint,{'thscode':code,'period':'quarterly','limit':limit})
    manifest=[]
    for p in sorted((ROOT/'02_原始数据').glob('*.json')):
        if p.name=='manifest.json':continue
        r=json.loads(p.read_text());payload=r.pop('payload',{});r.update({'business_code':payload.get('code'),'item_count':len((payload.get('data') or {}).get('item',[]))});manifest.append(r)
    save('02_原始数据/manifest.json',manifest)
if __name__=='__main__':collect()
