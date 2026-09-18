"""Packaging and JS state tests; these do not claim real-browser compatibility."""
import json
import re
import subprocess
import unittest
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup
from sources import ROOT, read
from report_comparison import BASELINE, PAIRS
from publish import markdown


class OfflineNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = ROOT / '06_交互图与研报/index.html'
        cls.soup = BeautifulSoup(cls.path.read_text(), 'html.parser')
        cls.embedded = json.loads(cls.soup.select_one('#temporalDocument').string)
        cls.temporal = BeautifulSoup(cls.embedded, 'html.parser')
        cls.script = cls.soup.find_all('script')[-1].string

    def test_sixth_entry_is_internal(self):
        tabs = self.soup.select('#tabs button[data-tab]')
        self.assertEqual(len(tabs), 6)
        self.assertEqual(tabs[-1]['data-tab'], 'temporal')
        self.assertIsNotNone(self.soup.select_one('main > #temporal #temporalFrame'))
        self.assertFalse(self.soup.select('#tabs a'))
        self.assertIn("'report','temporal'].includes(location.hash.slice(1))", self.script)

    def test_report_comparison_preserves_both_sources(self):
        rows = self.soup.select('#reportDifferences .comparison-row')
        self.assertEqual(len(rows), len(PAIRS))
        for row in rows:
            self.assertEqual(len(row.select('.comparison-excerpt')), 2)
            self.assertTrue(row.select('.baseline mark'))
            self.assertTrue(row.select('.enhanced mark'))
            self.assertIsNotNone(row.select_one('.difference-note'))
        for side, path in [('baseline', ROOT.parent / BASELINE), ('enhanced', ROOT / '06_交互图与研报/语义图增强版研报.md')]:
            expected = BeautifulSoup(markdown(path.read_text()), 'html.parser').get_text()
            actual = BeautifulSoup(str(self.soup.select_one('#reportFull article.' + side)), 'html.parser')
            actual.select_one('.side-caption').decompose()
            self.assertEqual(re.sub(r'\s+', '', actual.get_text()), re.sub(r'\s+', '', expected))
        self.assertNotIn('__REPORT_', str(self.soup))

    def test_report_comparison_citations_and_links(self):
        evidence = json.loads(self.soup.select_one('#baselineEvidence').string)
        baseline_ids = {x.get('source_id') or x.get('derived_id') for xs in evidence.values() for x in xs}
        data = read('05_图与查询/explorer_data.json')
        enhanced_ids = {x['id'] for x in data['claims'] + data['judgments']} | {x['derived_id'] for x in data['derived']}
        for link in self.soup.select('#report a[onclick]'):
            call, identifier = re.search(r"(showBaselineRef|showRef)\('([^']+)'\)", link['onclick']).groups()
            self.assertIn(identifier, baseline_ids if call == 'showBaselineRef' else enhanced_ids)
        for link in self.soup.select('#report a[href]'):
            if link['href'].startswith('#'):
                continue
            self.assertTrue((self.path.parent / unquote(link['href'])).resolve().exists())

    def test_report_view_switch_state(self):
        function = re.search(r'^function setReportView\(view\).*$', self.script, re.M)[0]
        result = subprocess.run(['node', '-e', r'''
const vm=require('node:vm'),assert=require('node:assert/strict'),fs=require('node:fs');
const elements=Object.fromEntries(['reportDifferences','reportFull'].map(id=>[id,{hidden:false,classList:{toggle(c,on){elements[id].hidden=on}}}]));
const buttons=['differences','full'].map(view=>({dataset:{reportView:view},setAttribute(k,v){this[k]=v}}));
const context={$:id=>elements[id],document:{querySelectorAll:()=>buttons}};
vm.createContext(context);vm.runInContext(fs.readFileSync(0,'utf8'),context);
context.setReportView('full');assert.equal(elements.reportDifferences.hidden,true);assert.equal(elements.reportFull.hidden,false);assert.equal(buttons[1]['aria-pressed'],'true');
context.setReportView('differences');assert.equal(elements.reportDifferences.hidden,false);assert.equal(elements.reportFull.hidden,true);assert.equal(buttons[0]['aria-pressed'],'true');
context.setReportView('invalid');assert.equal(elements.reportFull.hidden,true);
'''], input=function, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_embedded_data_matches_source(self):
        script = self.temporal.find('script').string
        data = json.JSONDecoder().raw_decode(script.split('const DATA=', 1)[1])[0]
        self.assertEqual(data, read('08_时态图与行业演化/时态图.json'))
        self.assertGreater(len(data['assertions']), 0)
        self.assertGreater(len(data['financial']), 0)
        self.assertEqual(len(data['series']), 4)
        self.assertFalse(self.temporal.select('script[src], iframe[src]'))

    def test_embedded_source_links_keep_original_base(self):
        base = urljoin(self.path.as_uri(), self.temporal.find('base')['href'])
        expected = (ROOT / '08_时态图与行业演化').as_uri() + '/'
        self.assertEqual(unquote(base), unquote(expected))
        for link in self.temporal.select('a[href]'):
            url = urljoin(base, link['href'])
            if urlparse(url).scheme == 'file':
                from pathlib import Path
                self.assertTrue(Path(unquote(urlparse(url).path)).exists(), url)

    def test_javascript_syntax_and_lazy_tab_switch(self):
        function = re.search(r'^function openTab\(tab\).*$', self.script, re.M)[0]
        payload = json.dumps({
            'scripts': [self.script, self.temporal.find('script').string],
            'function': function,
            'document': self.embedded,
        })
        result = subprocess.run(['node', '-e', r'''
const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const p=JSON.parse(fs.readFileSync(0,'utf8'));
p.scripts.forEach(s=>new vm.Script(s));
function node(id){return {id,dataset:{tab:id},classes:new Set(),classList:{toggle(c,on){on?this.owner.classes.add(c):this.owner.classes.delete(c)}}}}
const sections=['business','argument','queries','audit','report','temporal'].map(node);
const buttons=sections.map(n=>node(n.id));
[...sections,...buttons].forEach(n=>n.classList.owner=n);
let writes=0, value, argumentCalls=0, blockedHistory=false;
const frame={hasAttribute:()=>writes>0,set srcdoc(v){writes++;value=v}};
const context={
 document:{querySelectorAll:s=>s==='main>section'?sections:buttons},
 $:id=>id==='temporalFrame'?frame:{textContent:JSON.stringify(p.document)},
 argument:()=>argumentCalls++, location:{hash:''},
 history:{replaceState(a,b,h){if(blockedHistory){const e=new Error();e.name='SecurityError';throw e}context.location.hash=h}}
};
vm.createContext(context);vm.runInContext(p.function,context);
assert.equal(writes,0);
context.openTab('temporal');
assert.equal(value,p.document);assert.equal(writes,1);assert.equal(context.location.hash,'#temporal');
assert.deepEqual(sections.filter(n=>!n.classes.has('hidden')).map(n=>n.id),['temporal']);
assert.deepEqual(buttons.filter(n=>n.classes.has('active')).map(n=>n.id),['temporal']);
context.openTab('report');context.openTab('temporal');assert.equal(writes,1);
context.openTab('argument');assert.equal(argumentCalls,1);
blockedHistory=true;context.openTab('temporal');assert.equal(context.location.hash,'temporal');
console.log('Syntax, lazy initialization, retained iframe state, tab visibility and history fallback passed.');
'''], input=payload, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
