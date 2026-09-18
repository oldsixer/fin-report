"""Build a provenance-preserving temporal graph and its offline linked views."""
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / '06_半导体板块图研报实验' / '02_原始数据'
OUT = ROOT / '08_时态图与行业演化'
TZ = ZoneInfo('Asia/Shanghai')
INDEX_NAMES = {'881121.TI': '半导体', '884229.TI': '半导体设备',
               '884091.TI': '半导体材料', '000300.SH': '沪深300'}
FIELDS = {'revenue': ('income', 'operating_income', '营业收入'),
          'profit': ('income', 'parent_holder_net_profit', '归母净利润'),
          'ocf': ('cash', 'act_cash_flow_net', '经营现金流'),
          'capex': ('cash', 'pay_fixed_assets_etc_cash', '资本支出现金')}


def read(p):
    return json.loads(p.read_text())


def date(ms):
    return datetime.fromtimestamp(ms / 1000, TZ).date().isoformat() if ms else None


def save(name, data):
    OUT.mkdir(exist_ok=True)
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) if not isinstance(data, str) else data)


def main():
    original = read(ROOT / '05_图与查询/explorer_data.json')
    manifest = []

    def source(p):
        x = read(p)
        manifest.append({'path': str(p.relative_to(ROOT.parent)),
                         'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
        return x

    # Hash the exact curated graph input as well as every raw response consumed.
    manifest.append({'path': str((ROOT / '05_图与查询/explorer_data.json').relative_to(ROOT.parent)),
                     'sha256': hashlib.sha256((ROOT / '05_图与查询/explorer_data.json').read_bytes()).hexdigest()})
    entities = [dict(n) for n in original['nodes']]
    company_ids = {code: next(n['id'] for n in entities if n['label'] == name)
                   for code, name in original['sample_names'].items()}
    docs = [{k: v for k, v in d.items() if k != 'text'} for d in original['documents']]
    dm = {d['source_id']: d for d in docs}
    assertions = []
    for c, edge in zip(original['claims'], original['edges']):
        assert c['id'] == edge['claim_id']
        d = dm[c['source_id']]
        assertions.append({**c, 'source': edge['source'], 'target': edge['target'],
                           'company': d['company'], 'published_at': d['publication_date'],
                           'retrieved_at': d['retrieved_at'], 'value_time': c['time'],
                           'valid_from': None, 'valid_to': None,
                           'temporal_semantics': 'dated disclosure, not a continuing-state assertion'})
    observations, series, financial = [], {}, []
    for code, name in INDEX_NAMES.items():
        p = BASE / f'history_{code}.json'
        raw = source(p)
        entity = 'INDEX_' + code
        entities.append({'id': entity, 'label': name, 'type': '指数', 'code': code})
        rows = sorted(raw['payload']['data']['item'], key=lambda r: r['date_ms'])
        points = []
        for i, r in enumerate(rows):
            t = date(r['date_ms'])
            point = {'id': f'P_{code}_{t}', 'entity': entity, 'code': code,
                     'metric': 'close', 'unit': '点', 'value_time': t, 'value': r['close_price'],
                     'daily_return_pct': (r['close_price'] / rows[i-1]['close_price'] - 1) * 100 if i else None,
                     'rebased': r['close_price'] / rows[0]['close_price'] * 100,
                     'retrieved_at': raw['fetched_at'], 'published_at': None,
                     'raw_path': '../../06_半导体板块图研报实验/02_原始数据/' + p.name,
                     'raw_row_index': raw['payload']['data']['item'].index(r)}
            observations.append(point)
            points.append(point)
        series[code] = {'name': name, 'entity': entity, 'points': points}

    for code, name in original['sample_names'].items():
        grouped = defaultdict(dict)
        for kind in ('income', 'cash'):
            p = BASE / f'{kind}_{code}.json'
            raw = source(p)
            for i, r in enumerate(raw['payload']['data']['item']):
                assert r['currency'] == 'CNY' and r['period'] == 'quarterly'
                key = date(r['period_end_ms'])
                record = grouped[key]
                record.update({'code': code, 'name': name, 'entity': company_ids[code],
                               'period_end': key, 'period': str(r['fiscal_year']) + r['fiscal_period'],
                               'basis': 'year_to_date', 'unit': '亿元'})
                record[kind + '_vendor_date'] = date(r['report_date_ms'])
                record[kind + '_retrieved_at'] = raw['fetched_at']
                record[kind + '_raw'] = '../../06_半导体板块图研报实验/02_原始数据/' + p.name
                for metric, (typ, field, label) in FIELDS.items():
                    if typ != kind:
                        continue
                    value = r.get(field)
                    record[metric] = value / 1e8 if value is not None else None
                    observations.append({'id': f'V_{code}_{metric}_{key}', 'entity': company_ids[code],
                                         'code': code, 'metric': metric, 'label': label,
                                         'value_time': key, 'period': record['period'],
                                         'value': record[metric], 'unit': '亿元', 'basis': 'year_to_date',
                                         'vendor_report_date': date(r['report_date_ms']),
                                         'published_at': None, 'retrieved_at': raw['fetched_at'],
                                         'raw_path': record[kind + '_raw'], 'raw_field': field, 'raw_row_index': i})
        for r in grouped.values():
            r['vendor_date'] = max(filter(None, [r.get('income_vendor_date'), r.get('cash_vendor_date')]), default=None)
            r['cash_proxy'] = r['ocf'] - r['capex'] if r.get('ocf') is not None and r.get('capex') is not None else None
            financial.append(r)

    links = [{'source': o['id'], 'target': o['entity'], 'relation': 'OBSERVATION_OF'} for o in observations]
    channels = defaultdict(list)
    for o in observations:
        channels[(o['entity'], o['metric'])].append(o)
    for channel in channels.values():
        channel.sort(key=lambda o: o['value_time'])
        links.extend({'source': a['id'], 'target': b['id'], 'relation': 'NEXT_OBSERVATION',
                      'meaning': 'chronological order, not causation or same-year increment'}
                     for a, b in zip(channel, channel[1:]))
    data = {'schema_version': '1.0', 'snapshot_date': '2026-09-15',
            'names': original['sample_names'], 'company_ids': company_ids, 'entities': entities,
            'assertions': assertions, 'documents': docs, 'observations': observations,
            'temporal_links': links, 'series': series,
            'financial': sorted(financial, key=lambda r: (r['code'], r['period_end'])),
            'manifest': manifest,
            'limitations': ['不是严格 point-in-time 数据库', '披露时间不等于有效期',
                            '行情为抓取时的历史版本', '财务流量为累计值，非单季',
                            '同花顺财务未与交易所逐项核对', '公司文本自述未独立验证']}
    save('时态图.json', data)
    template = (ROOT / 'temporal.template.html').read_text()
    save('index.html', template.replace('__DATA__', json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')))
    print(json.dumps({'observations': len(observations), 'assertions': len(assertions),
                      'temporal_links': len(links), 'financial_period_records': len(financial),
                      'sources_hashed': len(manifest)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
