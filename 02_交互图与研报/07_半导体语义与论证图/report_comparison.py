"""Editorial comparison of two existing reports, not a controlled ablation."""
import html
import re

BASELINE = '06_半导体板块图研报实验/06_研报与对照/原始数据版研报.md'

# Verbatim, contiguous excerpts. Compilation fails if either source changes.
PAIRS = [
    {
        'title': '01 / 行业判断：行情观察 → 增加产业统计',
        'kind': '新增资料',
        'left': '故当前日内普涨与三个月区间承压可以同时成立，不能以单日反弹推导行业周期反转。[D009][D010][D011][D012][D013][D014][D015]',
        'right': '这里的billings是金额口径，不是实物设备出货量，也不等同于收入、验收或回款。SEMI将该表现解释为支持AI投资和全球AI计算基础设施建设的技术、产能解决方案需求加速，但这只是协会解释，不能据此确认因果（F059）。更不能把全球账单直接推演为中国市场需求，进而推成A股公司订单。',
        'left_marks': ['不能以单日反弹推导行业周期反转'],
        'right_marks': ['billings是金额口径', '更不能把全球账单直接推演为中国市场需求，进而推成A股公司订单'],
        'note': '原版已经区分日内与区间表现。增强版新增协会产业资料，并明确“全球统计 → 中国需求 → 公司订单”的推断边界；新增信息不能归因于图结构本身。',
    },
    {
        'title': '02 / 设备公司：财务指标 → 产品与工艺位置',
        'kind': '新增业务关系',
        'left': '中微公司收入同比34.89%、归母净利同比300.22%，毛利率39.74%、研发费率19.57%，但现金余量代理为-0.92亿元。[D005]',
        'right': '工艺顺序可由披露串成：PSE V300Gi对应深孔/TSV孔洞刻蚀，后续有去胶、清洗，PEALD绝缘层沉积，PVD阻挡层/种子层，继而电镀填充和铜退火（F110、F031—F040）。中微硅通孔刻蚀设备与TSV孔洞刻蚀具有术语和工艺相关性，但不代表性能等价、客户重叠或份额可比（F126）。',
        'left_marks': ['收入同比34.89%', '现金余量代理为-0.92亿元'],
        'right_marks': ['深孔/TSV孔洞刻蚀', 'PEALD绝缘层沉积', 'PVD阻挡层/种子层', '不代表性能等价、客户重叠或份额可比'],
        'note': '阅读单位由“公司有哪些财务指标”扩展到“产品承担哪道工艺”。关系更具体，但共同工艺不等于供应关系、性能等价或订单兑现。',
    },
    {
        'title': '03 / 澜起科技：公司增长 → 产品代际与商业化状态',
        'kind': '状态与时间限定',
        'left': '澜起科技收入同比26.66%、归母净利同比72.33%，现金余量代理10.73亿元。[D001][D002]',
        'right': '“第一代量产/采购”与“第二代送样”必须隔离。第二代送样仅建立商业化观察起点，不能归因2026H1营收；后续须见客户验证、量产、实际采购、产品收入拆分及回款，延期、替代或收入贡献不足均是反证（F016、D002、J03）。',
        'left_marks': ['收入同比26.66%', '现金余量代理10.73亿元'],
        'right_marks': ['“第一代量产/采购”与“第二代送样”必须隔离', '不能归因2026H1营收', '客户验证、量产、实际采购、产品收入拆分及回款'],
        'note': '原版没有把增长归因为某代产品，不能把它标成错误。增强版补充代际证据，把“不能归因”以及需要补证的商业化环节具体化。',
    },
    {
        'title': '04 / 封装与现金：财务约束 → 业务验证路径',
        'kind': '论证更具体',
        'left': '这反映同一报告期内经营现金流与资本性现金支出之间存在差异，不能把正经营现金流直接等同于自由现金流，也不能在缺少连续期对比时写成“现金改善”。',
        'right': '长电历史量产披露与负代理并存，下一步要以先进封装收入/利润拆分、资本开支项目、产能利用率及回款验证；若新增产能长期不达预期或回款恶化，则削弱论点（F112、D006、J04）。',
        'left_marks': ['不能把正经营现金流直接等同于自由现金流'],
        'right_marks': ['先进封装收入/利润拆分、资本开支项目、产能利用率及回款', '若新增产能长期不达预期或回款恶化，则削弱论点'],
        'note': '两版都保留了现金流口径约束。增强版把现金现象与历史技术披露并置，并指向特定业务的验证项；没有证明负现金余量由先进封装扩产造成。',
    },
    {
        'title': '05 / 客户关系：缺失清单 → 有限补齐，并保留缺口',
        'kind': '新增证据及边界',
        'left': '缺少订单、报价、产能利用率、库存、客户、产品、供需、政策和供应关系证据，不能据行情或财务共振断言行业周期反转。',
        'right': '其中客户边来自新浪转载的2025年报摘要、未交叉核验原PDF；它不是订单、价格、数量、认证状态或当前供货份额。验证需要双方最新披露、销售结构、硅片规格价格、认证和产能利用率；客户变化、份额下降、降价或良率问题均可反证（J05）。',
        'left_marks': ['客户、产品、供需、政策和供应关系证据'],
        'right_marks': ['未交叉核验原PDF', '不是订单、价格、数量、认证状态或当前供货份额'],
        'note': '增强版增加“沪硅披露中芯为客户”的有限证据，不是全面补齐供应链。原件尚未交叉核验，这个限制不能被一条客户边掩盖。',
    },
    {
        'title': '06 / 假设与反证：并非从无到有，而是细化到具体机制',
        'kind': '两版都有',
        'left': '验证方式是观察每家公司后续收入、归母利润、经营现金流、资本开支及负债率，而非只观察PE变化。反证触发包括：高估值样本盈利或现金质量走弱、正PE分布进一步上移但财务指标没有相应验证，或非正PE公司仍无法恢复盈利。',
        'right': '故两公司值得沿先进封装工艺继续研究，前提是产品仍有效供给、客户路线确需该设备；需以当期认证、交付、收入和客户工艺路线验证，若路线替代或验证失败则构成反证（J01）。',
        'left_marks': ['验证方式', '反证触发'],
        'right_marks': ['产品仍有效供给、客户路线确需该设备', '若路线替代或验证失败则构成反证'],
        'note': '原版已有两条条件论证及牛／基准／熊情景。增强的差别是把条件落到产品、客户路线与认证，不是首次引入假设或反证，也不能据此直接宣称论证质量更高。',
    },
    {
        'title': '07 / 估值与情景：增强版也有缩减',
        'kind': '原版覆盖更完整',
        'left': '主板块正PE样本的中位数92.36倍、Q1/Q3为49.31/179.51倍；设备交集正PE样本23家，中位111.08倍、Q1/Q3为89.77/250.45倍；材料交集正PE样本25家，中位146.55倍、Q1/Q3为94.00/238.22倍。[D016][D017][D018]',
        'right': '在该证据补足前，结论应维持为条件性研究框架，而非业绩预测、目标价或交易指令。',
        'left_marks': ['中位数92.36倍、Q1/Q3为49.31/179.51倍', '中位111.08倍', '中位146.55倍'],
        'right_marks': ['条件性研究框架'],
        'note': '增强版未保留原版完整的PE分布分析与牛／基准／熊情景章节，重心转向业务关系和证据边界。它不是原版所有信息的超集；两版都没有给出目标价或交易指令。',
    },
]


def render_comparison(baseline, enhanced, markdown):
    def render(text, marks, side):
        out = markdown(text)
        if side == 'baseline':
            out = out.replace("showRef('", "showBaselineRef('")
            out = re.sub(r'\bS\d{3}\b', lambda m: f'<a href="#" onclick="showBaselineRef(\'{m[0]}\');return false">{m[0]}</a>', out)
        for fragment in marks:
            assert fragment in text, fragment
            out = out.replace(html.escape(fragment), f'<mark class="diff-mark">{html.escape(fragment)}</mark>')
        return out

    rows = []
    for i, pair in enumerate(PAIRS, 1):
        assert pair['left'] in baseline, f'Baseline excerpt {i} no longer matches'
        assert pair['right'] in enhanced, f'Enhanced excerpt {i} no longer matches'
        rows.append(f'''<section class="comparison-row" id="report-difference-{i}">
<div class="comparison-topic"><h3>{html.escape(pair['title'])}</h3><span class="difference-kind">{html.escape(pair['kind'])}</span></div>
<div class="comparison-columns"><article class="comparison-excerpt baseline"><div class="side-caption">不增强 · 原始数据版原文节选</div>{render(pair['left'], pair['left_marks'], 'baseline')}</article>
<article class="comparison-excerpt enhanced"><div class="side-caption">增强 · 语义图版原文节选</div>{render(pair['right'], pair['right_marks'], 'enhanced')}</article></div>
<p class="difference-note"><b>差异解读</b> {html.escape(pair['note'])}</p></section>''')
    baseline_full = render(baseline, [], 'baseline')
    enhanced_full = render(enhanced, [], 'enhanced')
    for pair in PAIRS:
        for side, source in [('left', 'baseline'), ('right', 'enhanced')]:
            for fragment in pair[side + '_marks']:
                before = html.escape(fragment)
                after = f'<mark class="diff-mark">{before}</mark>'
                if source == 'baseline': baseline_full = baseline_full.replace(before, after)
                else: enhanced_full = enhanced_full.replace(before, after)
    return '\n'.join(rows), baseline_full, enhanced_full
