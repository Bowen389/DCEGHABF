"""Idempotent fixed-size paper account; report Top4 never limits the execution universe."""
from pathlib import Path
import json,math
import pandas as pd
from .engine import PRIORITY
FEE=.0003

def fresh(start):return {'schema':1,'initial_cash':200000.,'cash':200000.,'entry_budget':20000.,'principal_cost_cap':200000.,'max_new_daily':1,'start_session':start,'last_processed':None,'holdings':[],'trades':[],'decisions':[],'equity':[]}
def settle(account,asof,quotes,previous_report,calendar):
 a=json.loads(json.dumps(account))
 if a.get('last_processed')==asof:return a
 if asof<a['start_session']:return a
 if a.get('last_processed') and asof<a['last_processed']:raise ValueError('Refuse to rewind paper account')
 q=quotes[quotes.date==asof].set_index('key');buy=[];prev=calendar[calendar.index(asof)-1] if calendar.index(asof)>0 else None
 if previous_report and previous_report.get('asof')==prev and previous_report.get('status')=='complete':
  for tag in PRIORITY:
   if tag not in previous_report['modules']:continue
   for r in previous_report['modules'][tag]['candidates']:
    x=dict(r,signal_date=prev);reason=None
    if r['key'] not in q.index:reason='无有效开盘报价'
    elif any(h['key']==r['key'] for h in a['holdings']):reason='已持仓不加仓'
    elif any(z['key']==r['key'] for z in buy):reason='同股重复'
    else:
     quote=q.loc[r['key']];gap=float(quote.open/quote.prev_close-1);lo=r.get('gap_low');hi=r.get('gap_high');x['gap']=gap
     if (lo is not None and gap<lo) or (hi is not None and gap>=hi):reason='开盘缺口不合格'
     elif len(buy)>=1:reason='每日新增1只上限'
     else:buy.append(x)
    if reason:a['decisions'].append(dict(x,date=asof,reason=reason))
 else:a['decisions'].append({'date':asof,'reason':'前一交易日完整报告缺失：不虚构补买'})
 for r in buy:
  quote=q.loc[r['key']];price=float(quote.open);qty=int(20000/(price*(1+FEE))//100)*100;cost=qty*price*(1+FEE)
  if qty<100 or cost>a['cash']+1e-8 or sum(h['cost'] for h in a['holdings'])+cost>200000+1e-8:
   a['decisions'].append(dict(r,date=asof,reason='整手预算、现金或20万元本金额度不足'));continue
  ix=calendar.index(asof)+int(r['hold_after_buy']);target=calendar[ix] if ix<len(calendar) else None
  if target is None:raise ValueError('Calendar does not cover target exit')
  a['cash']-=cost;a['holdings'].append(dict(r,buy_date=asof,buy_price=price,shares=qty,cost=cost,target_exit=target,last_close=float(quote.close),last_quote_date=asof))
 remain=[]
 for h in a['holdings']:
  if h['key'] in q.index:
   h['last_close']=float(q.loc[h['key'],'close']);h['last_quote_date']=asof
   if asof>=h['target_exit']:
    proceeds=h['shares']*h['last_close']*(1-FEE);a['cash']+=proceeds;a['trades'].append(dict(h,sell_date=asof,sell_price=h['last_close'],proceeds=proceeds,pnl=proceeds-h['cost']));continue
  remain.append(h)
 a['holdings']=remain;nav=a['cash']+sum(h['shares']*h['last_close'] for h in remain);a['equity'].append({'date':asof,'cash':a['cash'],'nav':nav,'holdings':len(remain),'invested_cost':sum(h['cost'] for h in remain)});a['last_processed']=asof
 assert a['cash']>=-1e-7 and sum(h['cost'] for h in remain)<=200000+1e-7
 return a
