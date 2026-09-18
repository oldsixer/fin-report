"""Explicit, reviewed prototype curation. These corrections are NOT a learned algorithm."""
import copy,re
from sources import ROOT,save,read
def main():
    ds={d['source_id']:d for d in read('03_文本证据/selected_documents.json')};cs=read('04_抽取与校验/accepted_claims.json');log=[];out=[]
    split={'C010':['车身控制','车用照明','智能座舱','辅助驾驶','电机电源'], 'C019':['云计算','高性能计算'], 'C022':['下一代服务器','企业存储','加速系统'], 'C035':['网络通讯','移动终端','家用电器','人工智能','汽车电子'], 'C057':['2D集成','2.5D集成','3D集成'], 'C058':['高性能计算','人工智能','5G','汽车电子'], 'C060':['300mm半导体硅片','200mm及以下半导体硅片'], 'C061':['抛光片','外延片','SOI硅片','压电薄膜衬底材料'], 'C062':['存储芯片制造','逻辑芯片制造','硅光芯片制造','图像处理芯片制造','通用处理器芯片制造','功率芯片制造','射频芯片制造','模拟芯片制造','分立芯片制造'], 'C063':['中芯国际','华虹宏力','华润微'], 'C065':['单晶生长','切割','研磨','抛光','外延','SOI'], 'C066':['300mm近完美单晶生长','超平坦抛光工艺','极限表征']}
    def add(c,reason,parent=None):
        c=copy.deepcopy(c);c.pop('errors',None);old=c.get('id',parent)
        assert c['source_id'] in ds and c['quote'] in ds[c['source_id']]['text'],(old,c['quote'])
        c['parent_extraction_id']=parent or old;c['id']=f'F{len(out)+1:03}';c['span_start']=ds[c['source_id']]['text'].index(c['quote']);c['span_end']=c['span_start']+len(c['quote']);c['span_basis']='selected_document';c['curation']=reason;c['validation']='literal span checked; primary agent semantic review, not independent annotation'
        out.append(c)
        if reason!='保留，经语义复核':log.append({'claim_id':c['id'],'parent':c['parent_extraction_id'],'action':reason})
        return c
    for original in cs:
        c=copy.deepcopy(original);i=c['id'];reason='保留，经语义复核'
        if i in ['C037','C047']:
            log.append({'parent':i,'action':'删除：基地不是子公司，且地理信息不是本轮关键研究关系'});continue
        if i=='C017':c.update(subject='澜起科技',subject_type='公司',object='PCIe 5.0/CXL 2.0 Retimer',object_type='产品');reason='事件方向统一为公司宣布某产品量产'
        if i=='C018':c['relation']='升级自';reason='明确产品代际升级，避免含混的技术特征边'
        if i=='C022':reason='原文next-generation servers不能擅自限定为异构服务器'
        if i=='C042':c.update(relation='拟服务客户',status='计划或待审批',time='2015-10-17披露；以未来交易完成为条件');reason='未来有条件服务不是现有客户'
        if i=='C046':
            for product in ['8英寸晶圆代工','12英寸晶圆代工']:
                add({**c,'object':product,'object_type':'业务模式','relation':'提供服务'},'纠正晶圆代工服务不是销售半导体硅片产品')
            continue
        if i=='C048':c.update(subject='SEMI',subject_type='组织',object='2026Q2全球半导体设备账单额 US$40.53 billion');reason='保留账单billings原指标与原币种量纲，避免与实物出货量混淆'
        if i=='C049':c.update(subject='SEMI对2026Q2设备账单增长的解释',subject_type='事件',object='人工智能基础设施投资',object_type='应用',status='作者解释');reason='修复归因边目标；仅记录SEMI解释，不确证因果'
        if i=='C050':c.update(relation='采用统计口径',object='成员提交的全球半导体设备月度账单汇总');reason='口径不是一个已实现数值，避免滥用披露统计边'
        if i in ['C051','C052','C053','C054','C055']:
            c['object']={'C051':'2026年全球设备销售额 $165.9 billion；同比23.2%','C052':'2028年全球设备销售额 $229.5 billion','C053':'2026年WFE销售额 $143.9 billion；同比23.1%','C054':'2026年测试设备销售额 $15.3 billion；同比31.0%','C055':'2026年封装设备销售额 $6.7 billion；同比9.6%'}[i];c['time']='2026-07-14发布；预测期：'+original['time'];c['status']='预测';reason='恢复原文货币量纲，分别保留预测发布时点和目标期'
        if i=='C057':c['relation']='涵盖集成技术';reason='覆盖多种集成路线不表示各组件同时存在'
        if i=='C065':c.update(relation='计划研发',status='计划或待审批');reason='重点研发方向不等于已掌握或已有供给'
        if i=='C066':c['relation']='披露技术突破';reason='明确这是公司自述的技术突破，不是产品交付'
        if c['source_id']=='T07R':c['time']='2025年事实页；业务描述未标精确有效日（图表统计截至2025-06-30）';reason='不将页面图表统计截止日冒充所有业务描述的有效日'
        if i=='C070':c['subject']='MOCVD设备'
        if i in split:
            for obj in split[i]:
                x={**c,'object':obj}
                if i=='C061' and obj=='压电薄膜衬底材料':x.update(relation='布局产品',status='计划或待审批')
                add(x,reason+'；将明确枚举拆成原子关系')
        else:add(c,reason)
    # Repair rejected quotes only by verified contiguous selection, never a fuzzy accept.
    rejected=read('04_抽取与校验/rejected_claims.json')
    for ix,c in enumerate(rejected):
        c=copy.deepcopy(c)
        if c['source_id']=='T19':log.append({'parent':'rejected_T19','action':'保持拒收：风险引文原文中不存在，不通过近似匹配放行'});continue
        if c['source_id']=='PSE V300Gi':c['source_id']='T06'
        if c['source_id']=='T03':
            t=ds['T03']['text'];start=t.index('该套片专为');c['quote']=t[start:t.index('。',start)+1]
        if c['source_id']=='T18':
            t=ds['T18']['text']
            if c['relation']=='宣布量产':
                start=t.index('在高性能先进封装领域');c['quote']=t[start:t.index('。',start)+1];c.update(subject='长电科技',subject_type='公司',object='XDFOI',object_type='技术')
            else:
                start=t.index('长电科技聚焦关键应用领域');c['quote']=t[start:t.index('。',start)+1];c['object']='XDFOI';c['object_type']='技术'
        add(c,'修复已定位的来源ID/换行/截句错误，并核对真实原文',f'rejected_{ix+1}')
    def emit(sid,sub,rel,obj,st,ot,quote,time=None,qual='公司披露；仅证实所述能力或关系，不证明订单规模',status='公司披露'):
        if any(c['source_id']==sid and c['subject']==sub and c['relation']==rel and c['object']==obj for c in out):return
        add(dict(source_id=sid,subject=sub,relation=rel,object=obj,subject_type=st,object_type=ot,quote=quote,time=time or ds[sid].get('evidence_period') or ds[sid].get('publication_date') or '未标日期；2026-09-15抓取，不保证当前仍有效',qualifiers=qual,status=status),'分析者补充：原文支持的缺失连接，非模型自动产物','review_addition')
    # Restore company → equipment links, which the first pass left disconnected.
    for c in list(out):
        if c['source_id']=='T06' and c['relation']=='用于工艺':emit('T06','北方华创','提供产品',c['subject'],'公司','产品',c['quote'])
    t=ds['T03']['text'];q=next(c['quote'] for c in out if c['source_id']=='T03' and '8800' in c['quote'])
    emit('T03','澜起科技','宣布量产','第一子代MRCD和MDB套片','公司','产品',q,'2025-01-24披露；量产起始日期未知','该代已量产且获规模采购；不可转移到第二子代')
    q=next(c['quote'] for c in out if c['source_id']=='T02' and '包括 SPI NOR' in c['quote'])
    for obj in ['车规级SPI NOR Flash','车规级SPI NAND Flash']:emit('T02','兆易创新','提供产品',obj,'公司','产品',q)
    q=next(c['quote'] for c in out if c['source_id']=='T07R' and '硅通孔' in c['quote'])
    emit('T07R','中微公司','提供产品','中微公司硅通孔刻蚀设备','公司','产品',q,'2025年事实页；业务描述未标精确有效日')
    emit('T07R','中微公司','提供产品','中微公司等离子体刻蚀设备','公司','产品',q,'2025年事实页；业务描述未标精确有效日')
    emit('T07R','中微公司硅通孔刻蚀设备','用于工艺','TSV孔洞刻蚀','产品','工艺',q,'2025年事实页；业务描述未标精确有效日','硅通孔与TSV术语对齐；仅工艺能力相交，不代表设备性能等价')
    q=next(c['quote'] for c in out if c['source_id']=='T07R' and 'CCP高能' in c['quote'])
    emit('T07R','中微公司','提供产品','ICP低能等离子体刻蚀设备','公司','产品',q,'2025年事实页；业务描述未标精确有效日')
    q=next(c['quote'] for c in out if c['source_id']=='T19' and '广泛应用于' in c['quote'])
    # Full company/product sentence establishes the ownership of the named product family.
    t=ds['T19']['text'];start=t.index('公司现已构建');q=t[start:t.index('。',start)+1]
    emit('T19','沪硅产业','提供产品','沪硅产业半导体硅片','公司','产品',q,'2025年','报告产品矩阵，不把全体产品都配对到每个应用')
    # Two explicit article-level technology/application connections.
    t=ds['T06']['text'];start=t.index('TSV技术的应用场景');q=t[start:t.index('。',start)+1]
    for obj in ['高性能计算','消费电子','汽车电子','数据中心']:emit('T06','TSV','应用于',obj,'技术','应用',q,'2025-05-28','TSV技术的一般适用场景；不是北方华创逐领域订单')
    q=next(c['quote'] for c in out if c['source_id']=='T06' and c['object']=='TSV工艺全链条解决方案')
    emit('T06','TSV工艺全链条解决方案','提供技术','TSV','产品','技术',q,'2025-05-28','原文方案面向TSV；不推出所有应用均有公司商业交付')
    # Every retained relationship has a typed and directed definition for reuse.
    schema={rel:{'direction':'subject → object','meaning':rel,'allowed_type_pairs':sorted({c['subject_type']+'→'+c['object_type'] for c in out if c['relation']==rel})} for rel in sorted({c['relation'] for c in out})}
    schema['前序工艺']['meaning']='subject工艺先于object工艺；不是反方向。仅限本文所述流程。'
    save('04_抽取与校验/curated_claims.json',out);save('04_抽取与校验/curation_log.json',log);save('00_方案与说明/关系schema.json',schema)
    save('04_抽取与校验/语义校验说明.md',f'''# 语义复核与修订

CLI初抽77条：72条通过连续原文/来源检查，5条被拒收。主代理对全部抽取逐条阅读复核，修复其中4条的来源/引文格式错误，保留1条伪引文拒收。
本次通过显式规则和主代理判断修正服务/产品、计划/实现、客户条件、统计/预测、枚举对象等问题，并补齐有证据的断链。最终{len(out)}条原子关系。详见curation_log.json，所有新增均标记review_addition。
这里的“复核”不是独立人工双盲标注，也不是已训练的curator；不能报告准确率提升。实体枚举拆分会增加边数，不能当新知识数量。下一步需要将这些失败类型做成独立测试集。
中微2025事实页为转曲PDF，文本工具未获得文字；本轮对渲染页作视觉核对并保存选择性转录。文本offset定位到转录文件，另保留PDF页号1。长电文本定位到PDF第10页。沪硅2025年报摘要经新浪转载获取，原官方网站访问失败已保留失败记录；客户边应进一步与交易所PDF交叉核验。
''')
    print('curated',len(out),'relations',len(schema),flush=True)
if __name__=='__main__':main()
