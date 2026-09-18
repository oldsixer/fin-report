"""Public primary-source text collection. No vendor keys or private inputs."""
from pathlib import Path
import json,datetime as dt,hashlib,urllib.request,concurrent.futures,subprocess,re
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parent
def save(path,value):
    p=ROOT/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,ensure_ascii=False,indent=2) if not isinstance(value,str) else value,encoding='utf-8')
def read(path):return json.loads((ROOT/path).read_text())
SOURCES=[
 ('T01','兆易创新公司介绍','603986.SH','https://www.gigadevice.com/about/company-profile',None),
 ('T02','兆易创新汽车产品','603986.SH','https://www.gigadevice.com/product/automotive-products',None),
 ('T03','澜起第二子代MRCD/MDB送样','688008.SH','https://www.montage-tech.com/cn/Press_Releases/20250124','2025-01-24'),
 ('T04','澜起PCIe5.0 Retimer量产','688008.SH','https://www.montage-tech.com/Press_Releases/20230106','2023-01-06'),
 ('T05','北方华创产品服务','002371.SZ','https://www.naura.com/product/',None),
 ('T06','北方华创TSV先进封装方案','002371.SZ','https://www-a.naura.com/content/details_30_2309.html',None),
 ('T07','中微公司官方事实页','688012.SH','https://www.amec-inc.com/uploads/files/20250902/17568042727426.pdf',None),
 ('T08','通富微电公司介绍','002156.SZ','https://www.tfme.com/About.html',None),
 ('T09','通富与AMD历史交易公告','002156.SZ','https://www.tfme.com/news/400.html','2015-10-17'),
 ('T10','沪硅产业业务布局','688126.SH','https://www.nsig.com/en',None),
 ('T11','长电XDFOI方案','600584.SH','https://www.jcetglobal.com/kr/site/detailscon/823',None),
 ('T12','中芯国际公司介绍','688981.SH','https://www.smics.com/en/site/about_summary',None),
 ('T13','SEMI 2026Q2设备统计','SEMI','https://www.semi.org/en/semi-press-release/global-semiconductor-equipment-billings-increased-23-percent-year-over-year-in-q2-2026-semi-reports','2026-09-03'),
 ('T14','SEMI设备销售预测','SEMI','https://www.semi.org/en/semi-press-release/global-semiconductor-equipment-sales-forecast-to-reach-a-record-229-billion-dollars-in-2028-semi-reports','2026-07-14'),
 ('T07R','中微公司官方事实页（重试）','688012.SH','https://www.amec-inc.com/uploads/files/20250902/17568042727426.pdf',None),
 ('T10R','沪硅产业业务布局（重试）','688126.SH','https://www.nsig.com/en',None),
 ('T15','长电XDFOI封装技术论文','600584.SH','https://imapsjmep.org/article/73375-study-on-cpi-behaviors-of-x-dimension-fan-out-integration-xdfoi-packages','2022-12-01'),
 ('T16','上海新昇公司介绍与沪硅产业关系','688126.SH','https://www.zingsemi.com/about/about_xs/',None),
 ('T17','中微公司英文事实页','688012.SH','https://static.amec-inc.com/uploads/c99d51d37d754b90af8a01be5680499c.pdf',None),
 ('T18','长电科技2024半年度报告','600584.SH','https://www.jcetglobal.com/uploads/%26e9%2695%26bf%26e7%2694%26b5%26e7%26a7%2691%26e6%268a%26802024%26e5%268d%268a%26e5%26b9%26b4%26e6%268a%26a5.pdf',None),
 ('T19','沪硅产业2025年度报告摘要（新浪转载披露）','688126.SH','https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12103531&stockid=688126','2026-04-17'),
]
def fetch(spec):
    sid,title,company,url,date=spec;p=ROOT/f'02_文本原始资料/{sid}.json'
    if p.exists():return json.loads(p.read_text())
    meta={'source_id':sid,'title':title,'company':company,'url':url,'publication_date':date,'retrieved_at':dt.datetime.now(dt.timezone.utc).isoformat(),'source_class':'industry_association' if company=='SEMI' else 'company_disclosure'}
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 FinAgent Research','Accept':'text/html,application/pdf'}),timeout=35) as r:raw=r.read();meta['http_status']=r.status
        meta['sha256']=hashlib.sha256(raw).hexdigest();ext='.pdf' if raw[:4]==b'%PDF' else '.html';rawpath=ROOT/f'02_文本原始资料/{sid}{ext}';rawpath.parent.mkdir(parents=True,exist_ok=True);rawpath.write_bytes(raw);meta['raw_path']=str(rawpath.relative_to(ROOT))
        if ext=='.pdf':
            result=subprocess.run(['pdftotext','-layout',str(rawpath),'-'],capture_output=True,text=True,check=True);text=result.stdout;meta['extraction']='pdftotext -layout; page breaks retained'
        else:
            soup=BeautifulSoup(raw,'html.parser')
            for el in soup(['script','style','nav','header','footer','form','noscript']):el.decompose()
            main=soup.select_one('main') or soup.select_one('article') or soup.body or soup
            text='\n'.join(x.strip() for x in main.get_text('\n').splitlines() if x.strip());meta['extraction']='HTML main/article/body, navigation removed'
        meta['text_characters']=len(text);meta['text_path']=f'03_文本证据/{sid}.txt';save(meta['text_path'],text)
        if len(text)<100:meta['status']='insufficient_text'
        else:meta['status']='ok'
    except Exception as e:meta.update({'status':'failed','error_type':type(e).__name__,'http_status':getattr(e,'code',None)})
    save(p,meta);print(sid,meta['status'],meta.get('text_characters'),flush=True);return meta
def collect():
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:metas=list(pool.map(fetch,SOURCES))
    save('02_文本原始资料/manifest.json',metas)
    documents=[{**m,'text':(ROOT/m['text_path']).read_text()} for m in metas if m['status']=='ok']
    save('03_文本证据/documents.json',documents)
if __name__=='__main__':collect()
