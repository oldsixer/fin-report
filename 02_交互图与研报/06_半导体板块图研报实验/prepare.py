"""Build a common sector corpus and transparent derived statistics using stdlib."""
from pipeline import ROOT,save,SAMPLES,INDICES
import json,datetime as dt,statistics as st,math,hashlib
def read(path):return json.loads((ROOT/path).read_text())
def iso(ms):return dt.datetime.fromtimestamp(ms/1000,dt.timezone(dt.timedelta(hours=8))).isoformat() if ms else None
def numeric(x):return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
def ratio(a,b,scale=1):return a/b*scale if numeric(a) and numeric(b) and b!=0 else None
def prepare():
    responses={};flags=[]
    for p in sorted((ROOT/'02_原始数据').glob('*.json')):
        if p.name=='manifest.json':continue
        r=json.loads(p.read_text())
        if r.get('http_status')==200 and r.get('payload',{}).get('code')==0:responses[r['name'].replace('_retry1','')]=r
    sources=[];records=[];ids={}
    for name,r in sorted(responses.items()):
        sid=f'S{len(sources)+1:03d}';ids[name]=sid;data=r['payload'].get('data') or {}
        sources.append({'source_id':sid,'name':name,'url':r['url'],'fetched_at':r['fetched_at'],'data_time':iso(data.get('timestamp')),'raw_path':'02_原始数据/'+r['name']+'.body','sha256':r['sha256']})
        for i,item in enumerate(data.get('item',[])):
            include=True
            if name.startswith(('income_','cash_')):include=item.get('fiscal_year') in [2025,2026] and item.get('fiscal_period')=='Q2'
            elif name.startswith('balance_'):include=item.get('fiscal_year')==2026 and item.get('fiscal_period')=='Q2'
            elif name=='index_search':include=item.get('thscode') in INDICES
            if include:records.append({'record_id':f'{sid}_{i}','source_id':sid,'source_name':name,'json_pointer':f'/data/item/{i}','response_data_time':iso(data.get('timestamp')),'data':item})
    names={r['data']['thscode']:r['data']['name'] for r in records if r['source_name'].startswith('members_')}
    main={r['data']['thscode'] for r in records if r['source_name']=='members_881121.TI'}
    derived=[]
    def add(entity,label,metrics,formula,used):
        rid=[r['record_id'] for r in used];sids=sorted({r['source_id'] for r in used})
        metrics={k:round(v,6) if isinstance(v,float) else v for k,v in metrics.items()}
        derived.append({'derived_id':f'D{len(derived)+1:03d}','entity':entity,'label':label,'metrics':metrics,'formula':formula,'source_ids':sids,'input_record_ids':rid})
    def select(name,year=2026):return next((r for r in records if r['source_name']==name and r['data'].get('fiscal_year')==year),None)
    for code in SAMPLES:
        a=select('income_'+code);b=select('income_'+code,2025);c=select('cash_'+code);d=select('balance_'+code)
        if any(x is None for x in [a,b,c,d]):raise RuntimeError('Missing H1 input '+code)
        i,j,k,l=[r['data'] for r in [a,b,c,d]];rev=i['operating_income'];profit=i['parent_holder_net_profit']
        vals={'revenue_cny_100m':ratio(rev,1e8),'revenue_yoy_pct':(ratio(rev,j['operating_income'])-1)*100 if numeric(j['operating_income']) and j['operating_income']>0 else None,'parent_net_profit_cny_100m':ratio(profit,1e8),'profit_yoy_pct':(profit/j['parent_holder_net_profit']-1)*100 if numeric(j['parent_holder_net_profit']) and j['parent_holder_net_profit']>0 else None,'gross_margin_pct':ratio(rev-i['operating_costs'],rev,100),'parent_net_margin_pct':ratio(profit,rev,100),'rd_ratio_pct':ratio(i['research_and_development_expenses'],rev,100),'operating_cash_cny_100m':ratio(k['act_cash_flow_net'],1e8),'capex_cny_100m':ratio(k['pay_fixed_assets_etc_cash'],1e8),'ocf_less_capex_proxy_cny_100m':ratio(k['act_cash_flow_net']-k['pay_fixed_assets_etc_cash'],1e8),'liabilities_to_assets_pct':ratio(l['total_debt'],l['assets_total'],100)}
        if vals['profit_yoy_pct'] is None:flags.append(names[code]+'同期净利非正/缺失，不计算普通净利同比。')
        if abs(l['assets_total']-l['total_debt']-l['holder_equity_total'])>max(1,l['assets_total']*1e-6):flags.append(code+'资产负债权益勾稽未通过。')
        add(code,names[code]+'2026H1财务',vals,'金额原值/1e8；H1累计同比=本期/同期-1（基数>0）；毛利率=(收入-成本)/收入；归母净利率=归母净利/收入；研发费率=研发费用/收入；现金余量代理=OCF-购建长期资产现金，非严格FCFF；负债率=负债合计/资产。',[a,b,c,d])
    index_calcs={}
    for code,label in INDICES.items():
        rr=sorted([r for r in records if r['source_name']=='history_'+code],key=lambda r:r['data']['date_ms'])
        if len(rr)<2:raise RuntimeError('Missing index history '+code)
        prices=[r['data']['close_price'] for r in rr];peak=prices[0];mdd=0
        for value in prices:peak=max(peak,value);mdd=min(mdd,value/peak-1)
        metrics={'start':iso(rr[0]['data']['date_ms'])[:10],'end':iso(rr[-1]['data']['date_ms'])[:10],'observations':len(rr),'price_return_pct':(prices[-1]/prices[0]-1)*100,'max_drawdown_pct':mdd*100}
        add(code,label+'区间价格表现',metrics,'首末收盘价之比-1；最大回撤=min(收盘/截至当日最高收盘-1)；非含息收益。',rr);index_calcs[code]=derived[-1]
    for code in list(INDICES)[:-1]:
        x,y=index_calcs[code],index_calcs['000300.SH'];assert (x['metrics']['start'],x['metrics']['end'])==(y['metrics']['start'],y['metrics']['end'])
        add(code,INDICES[code]+'相对沪深300区间差值',{'return_difference_pp':x['metrics']['price_return_pct']-y['metrics']['price_return_pct']},'同一区间价格涨幅相减，百分点；不是风险调整alpha。',[r for r in records if r['source_name'] in ['history_'+code,'history_000300.SH']])
    # Full constituent statistics: retain null/negative denominators explicitly.
    for code in list(INDICES)[:-1]:
        members=[r for r in records if r['source_name']=='members_'+code];codes={r['data']['thscode'] for r in members}
        covered=codes&main
        pp=[r for r in records if r['source_name'].startswith('prices_') and r['data']['thscode'] in covered]
        vv=[r for r in records if r['source_name'].startswith('valuations_') and r['data']['thscode'] in covered]
        change=[r['data']['price_change_ratio_pct'] for r in pp if numeric(r['data'].get('price_change_ratio_pct'))]
        up=sum(x>0 for x in change);down=sum(x<0 for x in change);flat=sum(x==0 for x in change)
        pe=[r['data'].get('pe_ttm') for r in vv];pos=sorted(x for x in pe if numeric(x) and x>0)
        q=st.quantiles(pos,n=4,method='inclusive') if len(pos)>=2 else [None]*3
        metrics={'index_constituents_total':len(codes),'in_main_sector_count':len(covered),'excluded_outside_main':len(codes-main),'prices_returned':len(pp),'valid_price_change_count':len(change),'up':up,'down':down,'flat':flat,'up_ratio_valid_pct':ratio(up,len(change),100),'equal_weight_change_pct':st.mean(change) if change else None,'median_change_pct':st.median(change) if change else None,'valuation_returned':len(vv),'positive_pe_count':len(pos),'nonpositive_pe_count':sum(numeric(x) and x<=0 for x in pe),'missing_pe_count':sum(not numeric(x) for x in pe),'positive_pe_median':st.median(pos) if pos else None,'positive_pe_q1':q[0],'positive_pe_q3':q[2]}
        add(code,INDICES[code]+'成分横截面（与主板块交集）',metrics,'统计范围=该指数当前成分∩主半导体指数成分；涨幅统计仅有效值；上涨比例=上涨数/有效涨跌幅数；正PE中位数仅PE>0，非整体PE、非市值加权；四分位采用inclusive线性插值。',members+pp+vv)
    samples=derived[:8];used=[r for r in records if r['source_name'].startswith('income_') or (r['source_name'].startswith('cash_') and r['data'].get('fiscal_year')==2026)]
    add('SAMPLE8','八家公司财务样本概览',{'companies':8,'positive_operating_cash_count':sum(d['metrics']['operating_cash_cny_100m']>0 for d in samples),'negative_cash_proxy_count':sum(d['metrics']['ocf_less_capex_proxy_cny_100m']<0 for d in samples),'revenue_yoy_median_pct':st.median(d['metrics']['revenue_yoy_pct'] for d in samples)},'仅8家预设样本的计数和中位数；不代表188家或全板块整体利润。',used)
    limits=['仅使用本轮同花顺API，不引入公司官网、外部产业新闻或模型常识。','主板块以881121.TI当前成分定义；设备/材料统计为与主板块交集，指数全体区间行情与交集成分横截面必须区分。','全量主板块行情/估值与八家公司财务样本分开。无市值字段，不计算市值加权PE/权重/贡献；正PE中位数不是行业整体PE。','快照分批获得，data_time为响应中最新上游时间，并非每只股票逐条时间；不把快照写成官方收盘价。','中报流量按2026/2025H1累计；quarterly不等于单季度。总负债不是有息债务；OCF-capex代理不是严格FCFF。','财报日期来自当前版本，不保证最初可得时间，不是PIT回测。数值仅对接口和内部计算负责，未逐条对账交易所公告。','不以板块成分断言公司主营分类、客户、供应关系；没有订单/报价/产能利用率等直接证据，不宣称行业周期反转或给出目标价。','Raw与Graph获得相同记录和派生结果；后者增加图邻域组织。非等token预算、单次对照，不能据此证明图因果有效。']
    context={'topic':'半导体板块：行情广度、估值分布与财务质量','as_of':'2026-09-15','main_sector':'881121.TI','main_constituent_count':len(main),'sample_names':{c:names[c] for c in SAMPLES},'company_names':names,'index_names':INDICES,'quality_flags':flags,'method_limits':limits}
    for name,value in [('sources',sources),('records',records),('derived',derived),('context',context)]:save('03_规范化证据/'+name+'.json',value)
    save('05_隔离输入与运行记录/raw_input.json',{'context':context,'sources':sources,'records':records,'derived':derived})
    print('sources',len(sources),'records',len(records),'derived',len(derived),'flags',flags)
if __name__=='__main__':prepare()
