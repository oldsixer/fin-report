"""Local UI smoke test; does not access network or the API credential."""
from pipeline import ROOT,save
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page(viewport={'width':1450,'height':1000},device_scale_factor=1)
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto((ROOT/'06_研报与对照/index.html').as_uri())
    page.wait_for_timeout(500)
    assert page.locator('svg .node').count()>1,errors
    page.screenshot(path=str(ROOT/'06_研报与对照/图界面预览.png'),full_page=True)
    page.select_option('#focus','688012.SH')
    page.select_option('#mode','full')
    assert '中微' in page.locator('#detail h3').inner_text()
    assert page.locator('svg .node').count()>5
    page.locator('#search').fill('D005');page.locator('#search').press('Enter')
    assert 'D005' in page.locator('#detail').inner_text()
    page.locator('#reset').click()
    assert page.locator('#focus').input_value()=='881121.TI'
    before=page.locator('svg .node').count()
    page.locator('#sampleOnly').uncheck()
    assert page.locator('svg .node').count()>before
    for name in ['原始数据版研报','图信息版研报']:
        page.goto((ROOT/f'06_研报与对照/{name}.html').as_uri())
        assert page.locator('table').count()>=1
        page.locator('a.cite').first.click()
        assert page.url.split('#')[-1].startswith(('S','D'))
    assert not errors,errors
    save('06_研报与对照/ui_validation.json',{'passed':True,'js_errors':errors,'checks':['graph rendered','company selection','full provenance layer','search calculation','reset','two report tables','citation navigation']})
    browser.close()
print('UI checks passed')
