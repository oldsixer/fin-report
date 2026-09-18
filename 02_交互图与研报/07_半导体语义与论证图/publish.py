"""Offline HTML packaging; no external CDN or file:// fetch requirement."""
import html,json,re
from sources import ROOT,read,save
from report_comparison import BASELINE, render_comparison
def inline(s):
    s=html.escape(s);s=re.sub(r'\*\*(.+?)\*\*',r'<strong>\1</strong>',s)
    return re.sub(r'\b([FD]\d{3}|J\d{2})\b',lambda m:f'<a href="#" onclick="showRef(\'{m[1]}\');return false">{m[1]}</a>',s)
def markdown(t):
    ls=t.splitlines();out=[];i=0
    while i<len(ls):
        s=ls[i].strip()
        if not s:i+=1;continue
        if s.startswith('|'):
            rows=[]
            while i<len(ls) and ls[i].strip().startswith('|'):
                cells=[x.strip() for x in ls[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?',x) for x in cells):rows.append(cells)
                i+=1
            out.append('<div class="table-wrap"><table>'+''.join('<tr>'+''.join(f'<{"th" if j==0 else "td"}>{inline(c)}</{"th" if j==0 else "td"}>' for c in row)+'</tr>' for j,row in enumerate(rows))+'</table></div>');continue
        m=re.match(r'^(#{1,6}) (.*)',s)
        if m:out.append(f'<h{len(m[1])}>{inline(m[2])}</h{len(m[1])}>')
        elif s.startswith('- '):out.append('<p>• '+inline(s[2:])+'</p>')
        else:out.append('<p>'+inline(s)+'</p>')
        i+=1
    return '\n'.join(out)
def temporal_document():
    """Inline the temporal view so file viewers need not navigate sibling HTML files."""
    template=(ROOT/'temporal.template.html').read_text()
    payload=json.dumps(read('08_时态图与行业演化/时态图.json'),ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    page=template.replace('__DATA__',payload)
    # srcdoc inherits the parent URL; restore the original base for source links.
    page=page.replace('<head>','<head><base href="../08_时态图与行业演化/" target="_blank">',1)
    page=re.sub(r'<a class="toplink"[^>]*>.*?</a>','<span class="toplink">通过上方标签切换业务图与研报</span>',page,count=1)
    return page
def main():
    data=read('05_图与查询/explorer_data.json');report=(ROOT/'06_交互图与研报/语义图增强版研报.md').read_text()
    baseline=(ROOT.parent/BASELINE).read_text()
    comparison,baseline_html,enhanced_html=render_comparison(baseline,report,markdown)
    template=(ROOT/'explorer.template.html').read_text();page=template.replace('__REPORT__',markdown(report)).replace('__DATA__',json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c'))
    page=page.replace('__REPORT_COMPARISON__',comparison).replace('__BASELINE_REPORT__',baseline_html).replace('__ENHANCED_REPORT__',enhanced_html)
    page=page.replace('__BASELINE_EVIDENCE__',json.dumps({'sources':read('01_基线快照/sources.json'),'derived':read('01_基线快照/derived.json')},ensure_ascii=False).replace('<','\\u003c'))
    page=page.replace('__TEMPORAL_DOCUMENT__',json.dumps(temporal_document(),ensure_ascii=False).replace('<','\\u003c'))
    helper="""function showRef(id){if(CM[id])return showClaim(id);if(JM[id]){$('judgment').value=id;openTab('argument');return}const d=DATA.derived.find(x=>x.derived_id===id);$('modalContent').innerHTML='<h3>'+esc(id)+' · '+esc(d.label)+'</h3><pre>'+esc(JSON.stringify(d,null,2))+'</pre>';$('modal').showModal()}"""
    page=page.replace('</script></body>',helper+'</script></body>');save('06_交互图与研报/index.html',page)
    print('published',len(page),flush=True)
if __name__=='__main__':main()
