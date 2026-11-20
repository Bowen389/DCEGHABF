from .engine import PRIORITY,grouped_top4

def fmt(v,percent=False):return '缺失' if v is None else (f'{v:.2%}' if percent else f'{v:.4f}')
def gap(row):
 lo,hi=row.get('gap_low'),row.get('gap_high')
 if lo is None and hi is None:return '不限'
 if lo is None:return f'<{hi:.0%}'
 if hi is None:return f'≥{lo:.0%}'
 return f'[{lo:.0%},{hi:.0%})'
def candidates_table(rows):
 if not rows:return '无可展示候选。\n'
 lines=['| 排名 | 模块 | 代码 | 名称 | 评分 | 池内分位 | 评分门槛 | 次日开盘缺口 | 买入后持有 |','|---|---|---|---|---:|---:|---|---|---|']
 for i,r in enumerate(rows,1):lines.append(f"| {i} | {r['module']} | {r['code']} | {r['name']} | {fmt(r['score'])} | {fmt(r['percentile'],True)} | {'通过' if r['passes_score'] else '未过，仅观察'} | {gap(r)} | {r['hold_after_buy']}个交易日 |")
 return '\n'.join(lines)+'\n'
def markdown(report):
 e=report['environment'];reg=e['regime'];mods=report['modules'];u=[t for t in PRIORITY if t in mods and mods[t]['regime']=='U'];qs=[t for t in PRIORITY if t in mods and mods[t]['regime']==reg]
 lines=[f"# DCEGHABF｜{report['asof']}盘后候选",f"生成：{report['generated_at']}；数据状态：**{report['status']}**。",f"环境：**{reg}**；全A上涨宽度 **{e['breadth']:.2%}**；上证收盘 **{e['index_close']:.4f}**；MA20 **{e['ma20']:.4f}**。",f"下一交易日：**{report['next_session']}**。当前Q只展示{reg}，其余Q不展示。",'## 固定执行规则','初始20万元，每笔固定约2万元（含买费、100股整手），盈利不放大金额；未平买入成本合计≤20万元，每天最多新买1只。优先顺序 **D→C→E→G→H→A→B→F**。同日同股去重，已持仓不加仓，现金不足未成交。','A—F买后下一交易日收盘卖；G买后第2个交易日收盘卖；H买后第4个交易日收盘卖，无有效报价顺延。买卖各3bp、零滑点。','**盘后评分候选不是买入确认：次日开盘仍需核验缺口、持仓和现金。Top4仅展示，模拟执行读取全量合格候选，不能限制为Top4。**','## U模块合并Top4（评分已过、开盘待确认）',candidates_table(grouped_top4(mods,u)),f'## 当前{reg}模块合并Top4（评分已过、开盘待确认）',candidates_table(grouped_top4(mods,qs))]
 for title,tags in [('U：各模块Top4',u),(f'{reg}：各模块Top4',qs)]:
  lines+=['## '+title]
  for t in tags:
   m=mods[t];lines +=[f"### {t} · {m['id']}",f"完整基础池{m['pool_count']}只；可评分{m['score_valid']}只；覆盖{m['coverage']:.2%}；评分门槛合格{m['qualified_count']}只。以下包含观察候选，未过门槛不得买入。",(m.get('unscorable_reason') or ''),candidates_table(m['watch_top4'])]
 lines+=['## 组合优先Top4（去重、评分已过、开盘待确认）',candidates_table(grouped_top4(mods,list(PRIORITY))),'## 数据与模拟账户',f"模拟账户从{report['paper']['start_session']}开始；现金{report['paper']['cash']:.2f}元；持仓{len(report['paper']['holdings'])}笔；最近记账{report['paper']['last_processed'] or '尚未开始'}。"]
 if report['errors']:lines+=['### 数据问题']+['- '+str(x) for x in report['errors']]
 lines+=['沿用研究授权：原始未复权报价，忽略历史ST、公司行动及官方涨跌停成交执行；涨停仅10%近似，不保证真实可成交。任何缺失数据不填零、不使用旧日期冒充当前。','[规则及全部系数](../docs/RULES.md) · [模拟账户](../paper/account.json)']
 return '\n\n'.join(lines)+'\n'
