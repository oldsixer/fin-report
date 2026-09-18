"""Two graph projections of the same qualified claims; deterministic dependency queries."""
import json, hashlib, collections, itertools
from sources import ROOT,read,save

ALIASES={'AI':'人工智能','人工智能（AI）':'人工智能','HPC':'高性能计算','高性能计算（HPC）':'高性能计算','汽车':'汽车电子','MRDIMM内存模组':'DDR5 MRDIMM','DDR5多路复用双列直插内存模组（MRDIMM）':'DDR5 MRDIMM','TSV（硅通孔）':'TSV','等离子体刻蚀':'等离子体刻蚀工艺','车规级GD32 MCU':'车规级MCU','车规级GD32MCU':'车规级MCU','XDFOI®':'XDFOI','XDFOI® Chiplet高密度多维异构集成系列工艺':'XDFOI','XDFOI Chiplet高密度多维异构集成系列工艺':'XDFOI'}
def canon(s):return ALIASES.get(s,s)
def eid(label):return 'E'+hashlib.sha256(label.encode()).hexdigest()[:12]

def build():
    claims=read('04_抽取与校验/curated_claims.json');docs=read('03_文本证据/selected_documents.json');context=read('01_基线快照/context.json');derived=read('01_基线快照/derived.json');dmap={d['derived_id']:d for d in derived}
    names=context['sample_names'];docmap={d['source_id']:d for d in docs};nodes={};edges=[]
    def node(label,typ):
        label=canon(label);i=eid(label)
        if i not in nodes:nodes[i]={'id':i,'label':label,'type':typ,'types':[typ]}
        elif typ not in nodes[i]['types']:nodes[i]['types'].append(typ)
        return i
    for c in claims:
        c['subject']=canon(c['subject']);c['object']=canon(c['object']);s=node(c['subject'],c['subject_type']);t=node(c['object'],c['object_type'])
        edges.append({'id':c['id'],'source':s,'target':t,'relation':c['relation'],'claim_id':c['id'],'source_id':c['source_id'],'status':c['status'],'time':c['time'],'qualifiers':c['qualifiers']})
    for code,name in names.items():node(name,'公司')
    cmap={c['id']:c for c in claims}
    def pick(sid,term='',relation=None):
        result=[c['id'] for c in claims if c['source_id']==sid and (not term or term in c['subject']+' '+c['object']+' '+c['quote']) and (not relation or c['relation']==relation)]
        if not result:raise ValueError(f'Missing premise: {sid} {term} {relation}')
        return result
    judgments=[]
    def argument(i,title,premises,assumption,verify,refute,question):
        judgments.append({'id':i,'label':title,'type':'判断','premises':premises,'assumption':assumption,'verify':verify,'refute':refute,'question':question,'status':'有条件研究判断','authoring':'analyst-authored, evidence-linked; not a learned causal edge','logic':'all listed premise records must remain available; truth still conditional on assumptions'})
    a=pick('T06','PSE','用于工艺')[0];b=pick('T07R','硅通孔','用于工艺')[0];sample=pick('T03','第二子代','宣布送样')[0];jcet=pick('T18','XDFOI','宣布量产')[0];customer=pick('T19','中芯国际','披露客户')[0]
    argument('J01','北方华创与中微的硅通孔刻蚀能力值得沿先进封装工艺继续研究',[a,b],'披露中的相关设备仍在有效供给，目标客户工艺路线需要该类设备；不推出两家公司份额或技术等价。','核实当期产品认证、交付、收入与实际客户工艺路线。','相关路线改为不需要该工艺，或产品未获验证/被替代。','先进封装：从技术相关到业绩兑现，还缺什么？')
    argument('J02','行业设备景气与工艺暴露构成研究线索，不构成个股订单增长证明',['J01',pick('T13','40.53')[0]],'全球设备支出能传导到目标地区与工艺，并形成公司订单；这些环节尚无直接证据。','公司分产品订单、地区占比、验收节奏、在手订单及竞争格局。','全球增长集中在不覆盖的地区/产品，公司订单或验收不增长。','先进封装：从技术相关到业绩兑现，还缺什么？')
    argument('J03','澜起第二子代送样只建立商业化观察起点，不能据此归因2026H1收入',[sample,'D002'],'若讨论后续收益，须额外证明客户验证、量产、实际采购与产品收入；2025送样消息不能补足。','更新第二子代量产披露、客户采用、销售拆分与回款。','验证延期、产品替代或该代产品收入不足以贡献增长。','产品代际：送样能否等于收入兑现？')
    argument('J04','长电先进封装已有历史量产披露，但2026H1现金余量代理为负仍需解释',[jcet,'D006'],'历史量产持续有效；负现金代理可能来自扩产，但本图没有项目回报和投入归因，不能自动解释为利好或困境。','先进封装收入/利润拆分、项目资本开支、现金回收和产能利用率。','新增产能长期不达预期，回款恶化，投入回报无法覆盖资本成本。','产品代际：送样能否等于收入兑现？')
    argument('J05','沪硅产业披露中芯国际为客户，关系存在不等于当前订单额或业绩弹性',[customer,'D008','D003'],'客户身份延续且存在具体采购；金额、份额、产品规格、关联时间仍需新合同或分部披露。','双方披露交叉核实，硅片销售结构、价格、数量、认证与产能利用率。','客户变化、供货份额下降、降价或良率不足抵消产能扩张。','真实供应链：哪些连接有出处，哪些仍是猜测？')
    argument('J06','2015年AMD交易文本只能证明当时的拟交易和审批条件',[pick('T09','85','拟收购')[0],pick('T09',relation='须获批准')[0]],'不预设后来完成，也不预设至今持股/客户关系不变。','查找交割公告、历年股权结构与最新客户披露。','原交易取消或条件变化；需要新证据更新状态。','真实供应链：哪些连接有出处，哪些仍是猜测？')
    argument('J07','SEMI的2028年设备预测是情景背景，不能作为2026已实现收入',[pick('T14','229.5')[0],pick('T13','40.53')[0]],'预测口径与实现值分别保留；2028总销售预测和2026Q2账单统计不是同一观测。','跟踪预测修订、实际设备销售/账单以及分类口径。','预测下修、实际增长显著低于预测、指标口径不可直接比较。','统计与预测：时间和范围如何限制结论？')
    # Long-form assertion graph: premises point to judgments; assumptions are explicit.
    anodes=list(nodes.values())+[{'id':c['id'],'label':f"{c['subject']} → {c['relation']} → {c['object']}",'type':'证据断言','source_id':c['source_id']} for c in claims]
    anodes += [{'id':d['derived_id'],'label':d['label'],'type':'财务计算','metrics':d.get('metrics',{})} for d in derived]
    anodes += [{'id':d['source_id'],'label':d['title'],'type':'来源'} for d in docs]
    aedges=[{'source':c['source_id'],'target':c['id'],'relation':'披露支持','kind':'provenance'} for c in claims]
    for c in claims:
        aedges.extend([{'source':eid(c['subject']),'target':c['id'],'relation':'断言主体','kind':'semantic_role'},{'source':c['id'],'target':eid(c['object']),'relation':'断言对象','kind':'semantic_role'}])
    for d in derived:
        if d.get('entity') in names:aedges.append({'source':eid(names[d['entity']]),'target':d['derived_id'],'relation':'具有财务观测','kind':'semantic_role'})
    for j in judgments:
        anodes.append(j)
        aedges += [{'source':p,'target':j['id'],'relation':'论证前提','kind':'dependency'} for p in j['premises']]
        for k,rel,typ in [('assumption','前提假设','假设'),('verify','需要验证','验证'),('refute','潜在反证','反证')]:
            ni=j['id']+'_'+k;anodes.append({'id':ni,'label':j[k],'type':typ});aedges.append({'source':j['id'] if k=='verify' else ni,'target':ni if k=='verify' else j['id'],'relation':rel,'kind':'qualification'})
    # Explainable bounded path projection: never use customer links to imply capabilities.
    allowed={'提供产品','提供服务','提供技术','应用于','用于工艺','组成部分','技术特征','宣布量产','宣布送样'}
    adj=collections.defaultdict(list)
    for e in edges:
        if e['relation'] in allowed:adj[e['source']].append(e)
    paths={}
    for name in names.values():
        start=eid(name);queue=collections.deque([(start,[],{start})]);found={}
        while queue:
            n,path,seen=queue.popleft()
            if len(path)>=3:continue
            for e in adj[n]:
                target=e['target']
                if target in seen:continue
                p=path+[e['id']]
                if nodes[target]['type'] in ['应用','工艺','技术']:found.setdefault(target,p)
                queue.append((target,p,seen|{target}))
        paths[name]=found
    overlaps=[]
    for x,y in itertools.combinations(names.values(),2):
        for target in sorted(set(paths[x])&set(paths[y])):
            overlaps.append({'company_a':x,'company_b':y,'shared':nodes[target]['label'],'path_a':paths[x][target],'path_b':paths[y][target],'meaning':'披露的应用或工艺交集；不是交易、竞争强度或因果关系'})
    def affected(seed):
        visited={seed};changed=[]
        while True:
            new=[j['id'] for j in judgments if j['id'] not in visited and set(j['premises'])&visited]
            if not new:break
            changed+=new;visited.update(new)
        return changed
    intervention={'operation':'撤回证据，不改变世界事实，不生成替代值','seed':a,'affected':affected(a),'unaffected':[j['id'] for j in judgments if j['id'] not in affected(a)],'expected':['J01','J02'],'result':'须复核，不等于结论已被证伪','financial_nodes_unchanged':list(dmap)}
    tests=[]
    def test(name,ok,detail):tests.append({'name':name,'passed':bool(ok),'detail':detail})
    test('每条文本关系存在可定位连续原文',all(c['quote'] in docmap[c['source_id']]['text'] for c in claims),f'{len(claims)}条；视觉摘录按摘录文件校验，另已核对PDF原页。')
    test('八家样本均有公司相关文本',set(names).issubset({d['company'] for d in docs}),'按来源元数据覆盖；不等于所有业务完备。')
    test('第二子代未由送样误写成量产',not any(c['relation']=='宣布量产' and '第二子代' in c['object'] for c in claims),'保留2025-01-24送样状态，不推断当下仍未量产。')
    test('历史拟收购保留审批条件',bool(pick('T09',relation='须获批准')),'只回答2015公告中的状态。')
    test('预测没有混入统计',all(c['status']=='预测' for c in claims if c['relation']=='发布预测'),'协会预测不是实际值。')
    test('披露客户关系存在原文证据',cmap[customer]['relation']=='披露客户','沪硅→中芯；来自新浪转载的2025年度报告摘要，尚未交易所PDF交叉核验。')
    test('跨两层失效传播且不波及无关判断',set(intervention['affected'])=={'J01','J02'},'固定依赖图单元测试，非真实因果干预效果。')
    test('所有论证前提可解析',all(p in cmap or p in dmap or p in {x['id'] for x in judgments} for j in judgments for p in j['premises']),'禁止悬空证据引用。')
    # Evidence-backed queries; answers computed from graph, not a separate answer generator.
    queries=[{'question':'哪些具体设备对应TSV的哪些工艺？','claim_ids':pick('T06',relation='用于工艺'),'kind':'产品—工艺映射'},
      {'question':'澜起哪些是送样，哪些有量产披露？','claim_ids':[c['id'] for c in claims if c['source_id'] in ['T03','T04'] and c['relation'] in ['宣布送样','宣布量产']],'kind':'阶段及代际'},
      {'question':'XDFOI有什么应用，是否已有量产披露？','claim_ids':pick('T18','XDFOI'),'kind':'技术—应用—事件'},
      {'question':'八家样本之间有哪条具名客户关系？','claim_ids':[c['id'] for c in claims if c['relation']=='披露客户' and c['subject'] in names.values() and c['object'] in names.values()],'kind':'可追溯供应链'},
      {'question':'2015 AMD交易能否当成今天已完成交易？','claim_ids':pick('T09',relation='拟收购')+pick('T09',relation='须获批准'),'kind':'条件与时间'},
      {'question':'行业实现值和预测分别是什么口径？','claim_ids':[c['id'] for c in claims if c['relation'] in ['披露统计','发布预测']],'kind':'统计与预测分离'}]
    test('六个业务查询均返回证据',all(q['claim_ids'] for q in queries),'自选案例的查询可用性检查，不是盲测准确率。')
    stats={'business_nodes':len(nodes),'business_edges':len(edges),'business_relation_types':dict(collections.Counter(e['relation'] for e in edges)),'text_sources_used':len(docs),'text_claims':len(claims),'argument_nodes':len(anodes),'argument_edges':len(aedges),'judgments':len(judgments),'shared_capability_paths':len(overlaps),'tests_passed':sum(t['passed'] for t in tests),'tests_total':len(tests),'baseline':{'nodes':1197,'edges':3746,'relation_types':9,'bookkeeping_share_pct':88.81},'comparison_caveat':'新增图聚焦8家样本，旧图包含188成分；节点/边数量不可直接当质量对比。文本增加与表示变化尚未消融。'}
    data={'stats':stats,'nodes':list(nodes.values()),'edges':edges,'claims':claims,'documents':[{k:v for k,v in d.items() if k!='text'} for d in docs],'judgments':judgments,'argument_nodes':anodes,'argument_edges':aedges,'derived':derived,'queries':queries,'overlaps':overlaps,'intervention':intervention,'tests':tests,'sample_names':names,'aliases':ALIASES}
    save('05_图与查询/业务语义图.json',{'nodes':data['nodes'],'edges':edges})
    save('05_图与查询/限定断言与论证图.json',{'nodes':anodes,'edges':aedges})
    save('05_图与查询/跨公司应用工艺路径.json',overlaps);save('05_图与查询/查询与依赖测试.json',{'queries':queries,'tests':tests,'intervention':intervention,'stats':stats})
    save('05_图与查询/explorer_data.json',data)
    report=['# 建图验证与边界','',json.dumps(stats,ensure_ascii=False,indent=2),'','## 已执行检查']
    report += [f"- {'通过' if t['passed'] else '失败'}：{t['name']}。{t['detail']}" for t in tests]
    report += ['','## 不能据此声称的结论','测试不是独立人工标注的准确率，不证明文本抽取完整，也不证明图提升投资收益或报告质量。两种表示共享同一事实集；论证节点和假设由分析者编写，不是训练得到。失效传播是依赖维护，不是经济因果识别。财务沿用06供应商快照，尚未对账交易所公告。','', '## 下一步严格实验','固定本轮新增文本、财务和模型，以原文检索、三元组、限定断言+论证图做同证据预算消融；独立标注跨文档问题、事件更新与不应改变的判断，测证据召回、关系蕴含、时间条件正确率、修订定位精确率/召回率及无关修改率。']
    save('00_方案与说明/验证与边界.md','\n'.join(report));print(json.dumps(stats,ensure_ascii=False),flush=True)
    if not all(t['passed'] for t in tests):raise RuntimeError('Graph checks failed')
    return data
if __name__=='__main__':build()
