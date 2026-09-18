"""Render local reports, verify citations/tables, and expose transparent editorial corrections."""
from pipeline import ROOT,save
import re,json,html,hashlib,collections

def read(p):return json.loads((ROOT/p).read_text())
def esc(x):return html.escape(str(x))
def inline(s):
    s=re.sub(r'\[([SD])(\d{3})-\1(\d{3})\]',lambda m:''.join(f'[{m[1]}{i:03d}]' for i in range(int(m[2]),int(m[3])+1)),s)
    s=esc(s)
    s=re.sub(r'\*\*(.+?)\*\*',r'<strong>\1</strong>',s)
    s=re.sub(r'\[([SD]\d{3})\]',r'<a class="cite" href="#\1">[\1]</a>',s)
    s=re.sub(r'\[([^\]]+)\]\(([^)]+)\)',r'<a href="\2">\1</a>',s)
    return s
def markdown(text):
    lines=text.splitlines();out=[];i=0
    while i<len(lines):
        s=lines[i].strip()
        if not s:i+=1;continue
        if s.startswith('|'):
            rows=[]
            while i<len(lines) and lines[i].strip().startswith('|'):
                cells=[x.strip() for x in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?',c) for c in cells):rows.append(cells)
                i+=1
            out.append('<div class="tablewrap"><table>'+''.join('<tr>'+''.join(f'<{"th" if j==0 else "td"}>{inline(c)}</{"th" if j==0 else "td"}>' for c in row)+'</tr>' for j,row in enumerate(rows))+'</table></div>');continue
        m=re.match(r'^(#{1,6}) (.*)',s)
        if m:level=len(m[1]);out.append(f'<h{level}>{inline(m[2])}</h{level}>')
        elif s.startswith('- '):out.append('<p class="bullet">• '+inline(s[2:])+'</p>')
        else:out.append('<p>'+inline(s)+'</p>')
        i+=1
    return '\n'.join(out)
CSS='''body{font:16px/1.85 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;background:#f3f5ef;color:#213c35;margin:0}main{max-width:1160px;margin:30px auto;padding:40px 50px;background:white;border:1px solid #dfe6dc;border-radius:12px}h1{font-size:31px;line-height:1.4}h2{font-size:22px;margin-top:36px;padding-top:18px;border-top:1px solid #e4e9e0}a{color:#187767}nav{font-size:13px;display:flex;gap:20px}.notice{background:#fff8e7;border-left:3px solid #cc9a39;padding:16px;font-size:13px}.tablewrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:12px;line-height:1.6}th{background:#eaf1e9;text-align:left}td,th{padding:10px 8px;border-bottom:1px solid #dfe6dc;min-width:75px}td:first-child{font-weight:600}tr:nth-child(even){background:#f7f9f5}.cite{font-size:11px;white-space:nowrap;text-decoration:none}details{font-size:12px;border-bottom:1px solid #e6e9e2;padding:10px}summary{cursor:pointer}pre{white-space:pre-wrap;word-break:break-word;background:#f4f6f0;padding:15px}small{color:#63776a}.bullet{padding-left:12px}@media(max-width:800px){main{margin:0;padding:22px}h1{font-size:26px}}'''
def page(title,body):return f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title><style>{CSS}</style><main><nav><a href="index.html">← 知识图与实验入口</a><a href="原始数据版研报.html">Raw 研报</a><a href="图信息版研报.html">Graph 研报</a><a href="方法与结果审计.html">审计</a></nav>{body}</main></html>'

def publish():
    sources=read('03_规范化证据/sources.json');records=read('03_规范化证据/records.json');derived=read('03_规范化证据/derived.json');graph=read('04_知识图/graph.json');context=read('03_规范化证据/context.json')
    values={r['data']['thscode']:r for r in records if r['source_name'].startswith('valuations_')}
    allowed={s['source_id'] for s in sources}|{d['derived_id'] for d in derived};audit={}
    appendix='<h2>来源和计算公式</h2><p><small>S为接口响应，D为程序计算。点击报告引用跳转，再展开查看。来源存在不等于全文推理正确。</small></p>'
    for d in derived:appendix+=f'<details id="{d["derived_id"]}"><summary>{d["derived_id"]} · {esc(d["label"])}</summary><pre>{esc(json.dumps(d,ensure_ascii=False,indent=2))}</pre></details>'
    for s in sources:appendix+=f'<details id="{s["source_id"]}"><summary>{s["source_id"]} · {esc(s["name"])}</summary><p>采集：{esc(s["fetched_at"])}；响应数据时间：{esc(s["data_time"])}</p><a href="../{esc(s["raw_path"].replace(".body",".json"))}" target="_blank">原始响应与请求参数 ↗</a><p>{esc(s["url"])}</p><p>SHA256: {s["sha256"]}</p></details>'
    for mode,name in [('raw','原始数据版研报'),('graph','图信息版研报')]:
        folder=f'05_隔离输入与运行记录/report_{mode}_final';original=read(folder+'/output.json')['report_markdown']
        unknown=sorted(set(re.findall(r'\b[SD]\d{3}\b',original))-allowed)
        rows={}
        for line in original.splitlines():
            if not line.strip().startswith('|'):continue
            cells=[x.strip().replace('**','') for x in line.strip().strip('|').split('|')]
            company=re.sub(r'\[[^\]]*\]','',cells[0]).strip()
            if company in context['sample_names'].values():rows[company]=cells
        checks=[]
        for d in derived[:8]:
            code=d['entity'];company=context['sample_names'][code];m=d['metrics'];row=rows.get(company,[])
            numbers=[float(x.replace(',','')) for x in re.findall(r'[-+]?\d[\d,]*(?:\.\d+)?',re.sub(r'\[[^\]]*\]','', '|'.join(row[1:])))]
            expected=[m[k] for k in ['revenue_cny_100m','revenue_yoy_pct','parent_net_profit_cny_100m','operating_cash_cny_100m','ocf_less_capex_proxy_cny_100m']]+[values[code]['data']['pe_ttm']]
            citations='|'.join(row)
            ok=len(row)==7 and len(numbers)==6 and all(abs(a-b)<=.00501 for a,b in zip(numbers,expected))
            checks.append({'company':company,'reported':numbers,'expected':expected,'numeric_pass':ok,'row_source_ids_present':d['derived_id'] in citations and values[code]['source_id'] in citations})
        trace=[json.loads(l) for l in (ROOT/(folder+'/trace.jsonl')).read_text().splitlines() if l.startswith('{')]
        nontext=[e['item']['type'] for e in trace if e.get('item') and e['item']['type'] not in ['agent_message','reasoning']]
        usage=next(e['usage'] for e in trace if e['type']=='turn.completed')
        forbidden=[term for term in ['长江存储','YMTC','Xtacking','致态'] if term in original]
        audit[mode]={'usage':usage,'report_characters':len(original),'unknown_citations':unknown,'nontext_trace_items':nontext,'excluded_topic_hits':forbidden,'table_checks':checks,'table_values_checked':48,'all_table_values_match':all(c['numeric_pass'] for c in checks),'all_rows_have_sources':all(c['row_source_ids_present'] for c in checks),'prompt_characters':read(folder+'/run.json')['prompt_characters']}
        save('06_研报与对照/report_validation.json',audit)
        if unknown or nontext or forbidden or not audit[mode]['all_table_values_match'] or not audit[mode]['all_rows_have_sources']:raise RuntimeError('Report validation failed: '+mode)
        note='本轮重新生成的纯半导体板块研报。主板块188只成分的行情/估值与八家公司财务样本分开；数值未逐项对账交易所公告。财务表格已程序核对，全文判断仍需研究者复核。'
        save('06_研报与对照/'+name+'.md',original)
        save('06_研报与对照/'+name+'.html',page(name,'<p class="notice">'+esc(note)+'</p>'+markdown(original)+appendix))
    for s in sources:assert hashlib.sha256((ROOT/s['raw_path']).read_bytes()).hexdigest()==s['sha256']
    audit['integrity']={'source_hashes_checked':len(sources),'all_match':True,'same_evidence':read('04_知识图/validation.json')}
    save('06_研报与对照/report_validation.json',audit)
    template=(ROOT/'viewer.html').read_text();save('06_研报与对照/index.html',template.replace('__GRAPH_JSON__',json.dumps(graph,ensure_ascii=False).replace('<','\\u003c')))
    ratio=audit['graph']['usage']['input_tokens']/audit['raw']['usage']['input_tokens']
    text=f'''# 纯半导体板块：方法与执行审计

## 本轮重新做了什么

主板块是同花顺881121.TI的188只当前成分，全部获得行情和估值快照。设备指数884229.TI有26只成分，材料指数884091.TI有29只；本次都落入主板块，但两者不被当作互斥、穷尽分类。另取沪深300作价格表现基准。

全部接口数据本轮重新采集，没有复用上一轮快照、报告或官网正文。41次成功API响应，另1次网络失败随后重试成功。八家财务样本为兆易创新、澜起科技、中芯国际、北方华创、中微公司、长电科技、通富微电、沪硅产业。财务样本不是全板块财务汇总。

## 建图方法和边的含义

借鉴[FinKario](https://aclanthology.org/2026.acl-long.446.pdf)的属性—事件双结构。本轮来源全部为结构化API，用确定性映射，不再通过LLM提取官网信息，也不复现论文的完整检索或交易流程。

图包含1197节点、3746条去重关系：188个公司、4个指数、1个研究样本集合、41个来源、926个观测、2个报告期、16个财报版本事件、19个计算结果。保留当前成分、公司观测、报告期、披露版本、计算输入和来源关系。没有供应链边、因果边、GNN训练或自动学习权重。

示例一：半导体指数 → 成分公司 → 行情/估值观测 → 来源；D016再指向188家公司横截面统计的输入记录。例二：中微公司 → 2026H1财报版本 → 利润/现金流观测 → D005财务计算。事件日期只是供应商当前版本日期，不保证首次披露，不能做严格PIT回测。

界面默认只展示八家财务样本以避免188个成分挤在同一屏；取消勾选即可展示全体业务关系。完整JSON一直保留所有节点，切换完整图可追溯来源。

## Raw与Graph如何进入模型

两路共同资料为926条选定API记录和19组计算，包含完整区间指数K线、所有成分清单、全部主板块行情/估值、样本2025/2026H1流量和2026H1资产负债表；更早季度保存在原始响应中但不进入模型。

Raw按来源排列记录；Graph从图节点中恢复同一记录集、按实体邻域组织，并附加成员关系、披露事件等元数据。每个记录在各自输入中仅出现一次。逐条哈希、来源目录、派生计算一致性均通过。记录排序和图结构开销仍不同，因此不是等token预算实验。

同一本机Codex CLI配置gpt-5.6-terra / low，独立临时目录、关闭联网和工具。最终两次trace均无工具执行条目。用户API密钥未传入模型输入。

|最终运行|Raw|Graph|
|---|---:|---:|
|输入token|{audit['raw']['usage']['input_tokens']}|{audit['graph']['usage']['input_tokens']}|
|输出token|{audit['raw']['usage']['output_tokens']}|{audit['graph']['usage']['output_tokens']}|
|正文字符数|{audit['raw']['report_characters']}|{audit['graph']['report_characters']}|
|八家公司固定表格核对|48/48|48/48|
|无效引用ID|0|0|

图版输入token为Raw的{ratio:.2f}倍。此处只报告真实开销，不宣称图提高报告质量。没有独立人工盲评、重复随机种子实验或收益回测。

## 中间发现、修正和保留的运行记录

首轮Raw生成曾把沪硅产业负PE写成缺失，并将单时点上涨广度称为改善。核验后，对两路共同提示同时补充“负值不等于缺失、截面不等于变化”的要求，重新生成两份最终报告，而非只修一份。首轮output/trace保留在report_raw和report_graph目录，最终在report_raw_final和report_graph_final目录。最终阅读版不对模型正文做静默人工改写。

另外完善了D019样本收入同比中位数的逐记录依赖，把上年同期利润表加入input_record_ids；未改变任何数值。此项修正后重新构建两路输入、重跑最终生成。首轮输入另存为raw_input_initial/graph_input_initial，保证每次运行可追溯。

## 校验能力与边界

41份成功来源哈希一致；926条记录在两种表示中完全一致；所有边端点存在；两篇固定财务表格合计96个数值与输入按两位小数一致，且每行财务/估值引用均可定位。没有遗留上轮公司事件主题。

这些检查不是外部真值验证、全文语义评分或全部正文数字验算。尚未逐项对账交易所原始公告。负PE保留，不解释为便宜；正PE中位数仅在正值子集计算，不是行业整体PE。现金余量代理不是严格FCFF；资产负债表total_debt是负债合计。单日广度与财务共振不证明供需周期反转。

## 下一步应如何比较

本轮比上轮少了网页抽取压缩的信息差异，更适合观察来源顺序和实体邻域组织的差异。但单次长篇生成仍不足以评价算法贡献。后续可固定同一语义记录，增加线性三元组对照、多时点和重复运行，再评价口径混淆、负值保留、证据支持、条件判断与成本。
'''
    save('06_研报与对照/方法与结果审计.md',text);save('06_研报与对照/方法与结果审计.html',page('方法与结果审计',markdown(text)))
    print(json.dumps({k:{kk:vv for kk,vv in v.items() if kk!='table_checks'} for k,v in audit.items()},ensure_ascii=False,indent=2))

if __name__=='__main__':publish()
