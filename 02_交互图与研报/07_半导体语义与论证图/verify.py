"""Integrity, report numeric checks and offline-browser interaction smoke tests."""
import hashlib,json,re,difflib,urllib.parse
from pathlib import Path
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from sources import ROOT,read,save
def main():
    data=read('05_图与查询/explorer_data.json');result={};pagefile=ROOT/'06_交互图与研报/index.html'
    result['source_hashes']=[{'source_id':d['source_id'],'match':hashlib.sha256((ROOT/d['raw_path']).read_bytes()).hexdigest()==d['sha256']} for d in data['documents']]
    result['graph_endpoints']={}
    for f in ['业务语义图.json','限定断言与论证图.json']:
        g=read('05_图与查询/'+f);ids=[n['id'] for n in g['nodes']];result['graph_endpoints'][f]=len(set(ids))==len(ids) and all(e['source'] in ids and e['target'] in ids for e in g['edges'])
    result['baseline_snapshot_unchanged']=all((ROOT/'01_基线快照'/f).read_bytes()==(ROOT.parent/'06_半导体板块图研报实验/03_规范化证据'/f).read_bytes() for f in ['derived.json','sources.json','context.json'])
    report=(ROOT/'06_交互图与研报/语义图增强版研报.md').read_text();allowed={c['id'] for c in data['claims']}|{d['derived_id'] for d in data['derived']}|{j['id'] for j in data['judgments']}
    result['unknown_report_citations']=sorted(set(re.findall(r'\b(?:F\d{3}|D\d{3}|J\d{2})\b',report))-allowed);result['excluded_topic_present']=any(s in report+json.dumps(data,ensure_ascii=False) for s in ['长江存储','YMTC','Xtacking','致态'])
    table=[]
    for code,name in data['sample_names'].items():
        row=next(l for l in report.splitlines() if l.startswith('|'+name+'|'));cells=row.split('|');d=next(x for x in data['derived'] if x.get('entity')==code);expected=[d['metrics'][k] for k in ['revenue_cny_100m','operating_cash_cny_100m','ocf_less_capex_proxy_cny_100m']];actual=[float(x) for x in cells[2:5]]
        table.append({'company':name,'actual':actual,'expected':expected,'pass':all(abs(a-b)<=.00501 for a,b in zip(actual,expected)) and d['derived_id'] in row})
    result['report_table_24_values']=table
    original=read('04_抽取与校验/研报生成_增强图/output.json')['report_markdown']
    save('07_交付验证/研报人工式修订.diff',''.join(difflib.unified_diff(original.splitlines(True),report.splitlines(True),fromfile='CLI原始输出',tofile='交付复核稿')))
    browser_results={};errors=[];outdir=ROOT/'07_交付验证';outdir.mkdir(exist_ok=True)
    with sync_playwright() as p:
        b=p.chromium.launch(headless=True);page=b.new_page(viewport={'width':1512,'height':1100},device_scale_factor=1);page.on('pageerror',lambda e:errors.append(str(e)));page.goto(pagefile.as_uri());page.wait_for_selector('#businessGraph svg')
        browser_results['initial_graph_nodes']=page.locator('#businessGraph .node').count();page.screenshot(path=str(outdir/'01_业务语义图.png'))
        page.locator('#edgeRows button').first.click();browser_results['claim_modal']=page.locator('#modal').is_visible();page.locator('#modal>button').click()
        for name in data['sample_names'].values():
            page.select_option('#focus',name);assert page.locator('#edgeRows tr').count()>0,name
        browser_results['eight_company_filters']=True;page.select_option('#focus','ALL');browser_results['all_relations']=page.locator('#edgeRows tr').count()
        page.locator('button[data-tab="argument"]').click();page.locator('#withdraw').click();browser_results['withdraw_marks']=page.locator('#argumentGraph .node').filter(has_text='须复核').count();browser_results['withdraw_message']='J01、J02' in page.locator('#withdrawResult').inner_text();page.screenshot(path=str(outdir/'02_证据撤回传播.png'));page.locator('#restore').click();browser_results['restore_marks']=page.locator('#argumentGraph .node').filter(has_text='须复核').count()
        for j in data['judgments']:page.select_option('#judgment',j['id']);assert page.locator('#argumentGraph .node').count()>0
        page.locator('button[data-tab="queries"]').click();browser_results['query_cards']=page.locator('#queryCards>.card').count();page.locator('button[data-tab="audit"]').click();browser_results['source_rows']=page.locator('#sourceRows tr').count()
        page.locator('button[data-tab="report"]').click();browser_results['report_rows']=page.locator('.report tbody tr').count();page.locator('.report a').first.click();browser_results['report_citation_opens']=page.locator('#modal').is_visible()
        if page.locator('#modal').is_visible():page.locator('#modal>button').click()
        page.screenshot(path=str(outdir/'03_增强研报.png'))
        local_links=page.eval_on_selector_all('a[href]','xs=>xs.map(x=>x.getAttribute("href"))');missing=[]
        for href in local_links:
            if href.startswith(('http:','https:','#','javascript:')):continue
            target=(pagefile.parent/urllib.parse.unquote(href.split('#')[0])).resolve()
            if not target.exists():missing.append(href)
        browser_results['missing_local_links']=missing;browser_results['page_errors']=errors
        page.set_viewport_size({'width':390,'height':844});page.locator('button[data-tab="business"]').click();page.select_option('#focus','TSV');browser_results['mobile_page_overflow']=page.evaluate('document.documentElement.scrollWidth>innerWidth+2');page.screenshot(path=str(outdir/'04_窄屏检查.png'));b.close()
    result['browser']=browser_results
    result['pass']=all(x['match'] for x in result['source_hashes']) and all(result['graph_endpoints'].values()) and result['baseline_snapshot_unchanged'] and not result['unknown_report_citations'] and not result['excluded_topic_present'] and all(x['pass'] for x in table) and not errors and not browser_results['missing_local_links'] and browser_results['all_relations']==len(data['claims']) and browser_results['withdraw_marks']==3 and browser_results['restore_marks']==0 and not browser_results['mobile_page_overflow']
    save('07_交付验证/验证结果.json',result);print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result['pass']:raise RuntimeError('Verification failed')
if __name__=='__main__':main()
