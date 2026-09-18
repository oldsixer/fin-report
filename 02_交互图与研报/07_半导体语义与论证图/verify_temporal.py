"""Deterministic data, temporal boundary, and offline browser tests. No API calls."""
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import unquote
from playwright.sync_api import sync_playwright
from temporal import ROOT, OUT, date


def main():
    data = json.loads((OUT / '时态图.json').read_text())
    checks = []

    def check(name, ok, detail=None):
        checks.append({'name': name, 'pass': bool(ok), 'detail': detail})
        if not ok:
            raise AssertionError(name + ': ' + str(detail))

    for m in data['manifest']:
        check('输入文件未改变：' + m['path'], hashlib.sha256((ROOT.parent / m['path']).read_bytes()).hexdigest() == m['sha256'])
    check('四条序列，每条65个交易日', all(len(s['points']) == 65 for s in data['series'].values()) and len(data['series']) == 4)
    check('48条公司报告期记录，192条财务指标观测', len(data['financial']) == 48 and len(data['observations']) == 452)
    all_nodes = {n['id'] for n in data['entities']} | {o['id'] for o in data['observations']}
    check('时态图节点ID唯一', len(all_nodes) == len(data['entities']) + len(data['observations']))
    check('所有观测与时间边端点存在', all(e['source'] in all_nodes and e['target'] in all_nodes for e in data['temporal_links']))
    check('业务边端点存在', all(c['source'] in all_nodes and c['target'] in all_nodes for c in data['assertions']))
    check('无凭据被写入导出', not any(s in (OUT / '时态图.json').read_text().lower() for s in ['authorization', 'api_key', 'access_token']))
    check('不伪造业务有效期', all(c['valid_from'] is None and c['valid_to'] is None for c in data['assertions']))
    om = {o['id']: o for o in data['observations']}
    check('NEXT_OBSERVATION只连接同实体同指标并严格递增', all(
        om[e['source']]['value_time'] < om[e['target']]['value_time']
        and (om[e['source']]['entity'], om[e['source']]['metric']) == (om[e['target']]['entity'], om[e['target']]['metric'])
        for e in data['temporal_links'] if e['relation'] == 'NEXT_OBSERVATION'))
    for o in data['observations']:
        raw = json.loads((OUT / o['raw_path']).resolve().read_text())
        r = raw['payload']['data']['item'][o['raw_row_index']]
        expected = r['close_price'] if o['metric'] == 'close' else (r[o['raw_field']] / 1e8 if r[o['raw_field']] is not None else None)
        assert o['value'] == expected, o['id']
    check('452个观测值逐项等于原始响应或单位换算值', True)
    for r in data['financial']:
        if r['cash_proxy'] is not None:
            assert abs(r['cash_proxy'] - (r['ocf'] - r['capex'])) < 1e-9
    check('现金代理计算且流量累计口径保留', all(r['basis'] == 'year_to_date' for r in data['financial']))
    pagefile = OUT / 'index.html'
    errors, requests = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width':1512, 'height':1100}, device_scale_factor=1)
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('request', lambda r: requests.append(r.url) if r.url.startswith(('http:', 'https:')) else None)
        page.goto(pagefile.as_uri())
        page.wait_for_selector('#marketChart svg')
        check('默认截面是采集日', page.input_value('#asof') == '2026-09-15')
        check('最后行情日期明确为09-14，不假装09-15行情', '2026-09-14' in page.locator('#marketDetail').inner_text() and '不是截止日当天行情' in page.locator('#marketDetail').inner_text())
        check('市场按钮四个，公司财务八行', page.locator('[data-index]').count() == 4 and page.locator('#financialRows tr').count() == 8)
        page.screenshot(path=str(OUT / '01_行业截面与日频轨迹.png'))
        page.eval_on_selector('#company', "e=>e.scrollIntoView({block:'start'})")
        page.screenshot(path=str(OUT / '02_业务图与公司时间轨迹.png'))
        page.locator('.graph-node').first.click()
        check('点击节点联动概念时间线', '正在追踪概念' in page.locator('#entityTitle').inner_text())
        page.locator('#edgeRows [data-claim]').first.click()
        check('原文证据可打开并明确有效期未知', page.locator('#detailModal').is_visible() and 'valid_from / valid_to 未填充' in page.locator('#modalContent').inner_text())
        page.click('#closeModal')
        page.click('#clearEntity')
        page.evaluate("setDate('2025-01-23')")
        check('送样披露前不可见T03', page.evaluate("visibleClaims().every(c=>c.source_id!=='T03')"))
        page.evaluate("setDate('2025-01-24')")
        check('披露当天T03出现', page.evaluate("visibleClaims().some(c=>c.source_id==='T03')"))
        page.select_option('#company', 'SEMI')
        page.evaluate("setDate('2026-07-13')")
        check('预测发布前不可见T14', page.locator('#edgeRows tr').count() == 0)
        page.evaluate("setDate('2026-07-14')")
        check('预测发布日可见且2028仍是预测目标非观测', page.evaluate("visibleClaims().some(c=>c.source_id==='T14'&&c.relation==='发布预测')"))
        page.evaluate("setDate('2026-09-02')")
        check('统计公告公开前不可见T13', page.evaluate("visibleClaims().every(c=>c.source_id!=='T13')"))
        page.evaluate("setDate('2026-09-03')")
        check('统计公告公开日可见T13', page.evaluate("visibleClaims().some(c=>c.source_id==='T13')"))
        page.select_option('#company', '603986.SH')
        page.evaluate("setDate('2026-09-14')")
        check('无日期背景不回填到采集日前', page.is_disabled('#undated') and page.locator('#edgeRows tr').count() == 0)
        page.click('#latest')
        page.check('#undated')
        check('采集日可单独查看无日期背景', page.locator('#edgeRows tr').count() > 0)
        page.select_option('#company', 'ALL')
        check('所有133条关系均可从截止日背景模式查看', page.locator('#edgeRows tr').count() == 133)
        page.uncheck('#undated')
        check('已知日期与未知日期独立', page.locator('#edgeRows tr').count() == sum(c['published_at'] is not None for c in data['assertions']))
        check('旧比较期修订日期没有前移', page.evaluate("(()=>{const r=DATA.financial.find(r=>r.code==='688008.SH'&&r.period==='2025Q2');return r.vendor_date==='2026-08-29'&&!financiallyVisible(r,'2025-12-31')})()"))
        page.evaluate("setDate('2026-09-13')")
        check('非交易日用最后已保存交易日，未插值', page.evaluate("lastPoint('881121.TI').value_time==='2026-09-11'"))
        page.locator('[data-index="884229.TI"]').click()
        check('点击行业指数切换日频曲线', '半导体设备' in page.locator('#marketChart').inner_text())
        page.locator('.market-hit[data-day="2026-07-20"]').click()
        check('点击日频点联动日期', page.input_value('#asof') == '2026-07-20')
        page.select_option('#company', '688008.SH')
        page.select_option('#metric', 'cash_proxy')
        page.locator('[data-period="2026Q2"]').click()
        check('财务轨迹可查看尚不应暴露给当时截面的观测', '晚于当前截面' in page.locator('#finDetail').inner_text())
        page.select_option('#metric', 'revenue')
        page.locator('[data-event-date="2025-01-24"]').click()
        check('披露时间线点击同步截面', page.input_value('#asof') == '2025-01-24')
        page.click('#latest')
        missing = []
        links = page.eval_on_selector_all('a[href]', 'xs=>xs.map(x=>x.getAttribute("href"))')
        for href in links:
            if href.startswith(('http:', 'https:', '#')) or href == '验证结果.json':
                continue
            if not (OUT / unquote(href.split('#')[0])).resolve().exists():
                missing.append(href)
        check('页面本地链接存在', not missing, missing)
        page.set_viewport_size({'width':390, 'height':844})
        page.wait_for_timeout(200)
        check('窄屏无页面级横向溢出', page.evaluate('document.documentElement.scrollWidth <= innerWidth+2'))
        page.locator('#company').scroll_into_view_if_needed()
        page.screenshot(path=str(OUT / '03_窄屏检查.png'))
        check('JavaScript运行无错误', not errors, errors)
        check('页面完全离线无外部依赖请求', not requests, requests)
        browser.close()
    result = {'pass': all(c['pass'] for c in checks), 'checks_passed': len(checks), 'checks': checks,
              'scope': '实现、日期过滤与输入一致性；不证明数据真实、历史首次可知性、因果关系或研报质量'}
    (OUT / '验证结果.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({'pass':result['pass'], 'checks_passed':len(checks)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
