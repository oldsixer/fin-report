"""Illustrative report from the enriched graph; not a controlled efficacy experiment."""
import json
from sources import ROOT,save,read
from extract import invoke
def main():
    data=read('05_图与查询/explorer_data.json')
    payload={k:data[k] for k in ['claims','judgments','derived','sample_names']}
    payload['source_notes']=[{k:d.get(k) for k in ['source_id','title','url','publication_date','evidence_period','source_class']} for d in data['documents']]
    prompt='''仅根据以下数据写约2200—3200字中文半导体板块研究示范报告。禁止工具和外部知识。标注“截至2026-09-15的证据整理；财务为2026H1；技术文本多为历史披露”。
主题：从行业景气，经公司产品/工艺/应用，到有条件业绩判断与风险。使用图中的Fxxx原子事实、Dxxx财务、Jxx条件判断，逐段近处引用。引用Jxx不替代事实证据。不得把未来/预测/公司自述/历史交易说成当前实现，不能编造供应链，只有沪硅→中芯等显式披露客户边可引用且须说明是新浪转载的2025年报摘要、未交叉核验原PDF。
含1核心判断；2行业统计与预测的口径分离（billings账单不是实物出货量，全球不能推成A股订单）；3按产品工艺角色串联8家公司而非简单罗列财务；4四条分析链（设备与TSV，澜起代际，封装与现金，硅片客户关系）；5事实、假设、验证、反证清单；6覆盖不足与下一步数据。
要求一张8公司H1财务小表：营收亿元、经营现金流亿元、现金余量代理亿元，保留两位小数，固定sample_names顺序，逐行D001-D008。现金余量=OCF-购建长期资产现金，不是严格FCFF。负值不自动等于困境。金额与同比不得凭记忆补写。单期不能写改善，未有产品收入拆分不能将总收入归因某代产品。不要目标价、交易指令，也不要宣称图更优。
判定图只是证据组织及依赖维护工具，不是因果已识别。本报告由同一CLI模型根据人工复核事实及分析者编写的条件论证生成，不是独立研究员验证。
输出JSON report_markdown。数据：'''+json.dumps(payload,ensure_ascii=False)
    r=invoke('研报生成_增强图',prompt,{'type':'object','properties':{'report_markdown':{'type':'string'}},'required':['report_markdown'],'additionalProperties':False})
    save('06_交互图与研报/语义图增强版研报.md',r['report_markdown'])
if __name__=='__main__':main()
