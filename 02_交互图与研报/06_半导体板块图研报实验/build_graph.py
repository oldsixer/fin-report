"""Typed attribute/event/provenance graph; exact same evidence for both report routes."""
from pipeline import ROOT,save,INDICES,SAMPLES
from prepare import read,iso
import json,hashlib,collections
def build():
    context=read('03_规范化证据/context.json');sources=read('03_规范化证据/sources.json');records=read('03_规范化证据/records.json');derived=read('03_规范化证据/derived.json')
    nodes={};edges=[];owned=collections.defaultdict(list)
    def node(id,type,label,**kw):
        if id not in nodes:nodes[id]={'id':id,'type':type,'label':label,**kw}
        return id
    def edge(a,rel,b,**kw):edges.append({'source':a,'relation':rel,'target':b,**kw})
    for c,n in context['company_names'].items():node(c,'company',n,financial_sample=c in SAMPLES)
    for c,n in INDICES.items():node(c,'index',n)
    node('SAMPLE8','concept','八家公司观察样本',semantics='非随机财务样本，不等于主板块整体')
    for c in SAMPLES:edge(c,'IN_RESEARCH_SAMPLE','SAMPLE8')
    for s in sources:node(s['source_id'],'source',s['source_id']+' '+s['name'],**s)
    for r in records:
        rid=r['record_id'];name=r['source_name'];d=r['data'];owner=d.get('thscode')
        if name.startswith('history_'):owner=name.split('_',1)[1]
        if owner not in nodes:raise ValueError('Unknown entity '+str(owner))
        owned[owner].append(rid)
        kind='利润表' if name.startswith('income_') else '资产负债表' if name.startswith('balance_') else '现金流量表' if name.startswith('cash_') else '指数成分' if name.startswith('members_') else '估值快照' if name.startswith('valuations_') else '行情记录' if name.startswith(('prices_','history_')) or name=='index_snapshot' else '指数元信息'
        period=f"{d.get('fiscal_year','')}{d.get('fiscal_period','')}";day=iso(d.get('date_ms'))
        node(rid,'observation',nodes[owner]['label']+' '+(period or (day or '')[:10])+' '+kind,record=r)
        edge(owner,'HAS_OBSERVATION',rid);edge(rid,'SUPPORTED_BY',r['source_id'],json_pointer=r['json_pointer'])
        if name.startswith('members_'):edge(owner,'MEMBER_OF',name.split('_',1)[1],source_id=r['source_id'],record_id=rid,as_of=r['response_data_time'])
        if d.get('fiscal_year'):
            pid='PERIOD:'+period;node(pid,'period',period+'报告期',semantics='Q2流量为累计中报，不是单季度')
            edge(rid,'FOR_PERIOD',pid)
            date=iso(d.get('report_date_ms'));eid=f'DISC:{owner}:{period}:{date}'
            node(eid,'event',nodes[owner]['label']+' '+period+'财报版本',event_date=date,semantics='供应商当前财报版本日期；不保证初次披露时间')
            edge(owner,'HAS_DISCLOSURE',eid);edge(eid,'HAS_OBSERVATION',rid);edge(eid,'FOR_PERIOD',pid)
    for d in derived:
        did=d['derived_id'];node(did,'calculation',d['label'],**{k:v for k,v in d.items() if k!='label'});edge(d['entity'],'HAS_CALCULATION',did)
        for rid in d['input_record_ids']:edge(did,'USES_RECORD',rid)
        for sid in d['source_ids']:edge(did,'COMPUTED_FROM_SOURCE',sid)
    unique={json.dumps(e,sort_keys=True,ensure_ascii=False):e for e in edges};edges=[{'id':f'E{i+1:05d}',**e} for i,e in enumerate(unique.values())]
    graph={'schema_version':'2.0-sector','semantics':'确定性构造的属性—财报事件—计算—溯源图；关系不表示因果或供应链。','context':context,'nodes':list(nodes.values()),'edges':edges}
    save('04_知识图/graph.json',graph)
    groups=[]
    for owner,rids in sorted(owned.items()):
        sem=[e for e in edges if e['source']==owner and e['relation'] in ['MEMBER_OF','HAS_CALCULATION','HAS_DISCLOSURE','IN_RESEARCH_SAMPLE']]
        event_ids={e['target'] for e in sem if e['relation']=='HAS_DISCLOSURE'}
        groups.append({'entity':nodes[owner],'records':[nodes[rid]['record'] for rid in rids],'semantic_relations':sem,'disclosure_events':[nodes[i] for i in sorted(event_ids)]})
    raw=read('05_隔离输入与运行记录/raw_input.json');graph_input={'context':context,'sources':sources,'entity_neighborhoods':groups,'derived':derived,'relation_semantics':graph['semantics']}
    save('05_隔离输入与运行记录/graph_input.json',graph_input)
    def canonical(rows):return {r['record_id']:hashlib.sha256(json.dumps(r,sort_keys=True,ensure_ascii=False).encode()).hexdigest() for r in rows}
    recovered=[r for g in groups for r in g['records']]
    assert len(recovered)==len(records) and canonical(recovered)==canonical(records)==canonical(raw['records'])
    assert graph_input['derived']==raw['derived'] and graph_input['sources']==raw['sources']
    assert all(e['source'] in nodes and e['target'] in nodes for e in edges)
    validation={'nodes':len(nodes),'edges':len(edges),'node_types':dict(collections.Counter(n['type'] for n in nodes.values())),'raw_records':len(records),'graph_records':len(recovered),'every_record_hash_matches':True,'same_derived':True,'same_sources':True,'all_edge_endpoints_exist':True,'financial_samples':len(SAMPLES),'main_constituents':context['main_constituent_count'],'method':'结构化API确定性映射；无文本抽取、GNN、自动因果推断；按实体组织输入，不重复提供同一记录。'}
    save('04_知识图/validation.json',validation);print(json.dumps(validation,ensure_ascii=False,indent=2))
if __name__=='__main__':build()
