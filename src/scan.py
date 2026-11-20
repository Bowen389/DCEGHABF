import argparse,json,traceback
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
from .engine import load_models,contract_hash,compute_pools,attach_turnover_to_breakout,score_modules
from .providers import CAL,sessions,next_session,load_history,fetch_turnover,atomic_json
from .paper import fresh,settle
from .reporting import markdown
ROOT=Path(__file__).resolve().parents[1]
def scan(root=ROOT,asof=None,if_needed=False,raw_override=None):
 root=Path(root);atomic_json(root/'reports/trading_calendar.json',{'source':'exchange_calendars XSHG','valid_from':'2023-01-03','valid_through':CAL.last_session.strftime('%Y-%m-%d'),'sessions':sessions('2023-01-03',CAL.last_session.strftime('%Y-%m-%d'))});now=datetime.now(ZoneInfo('Asia/Shanghai'));date=asof or now.date().isoformat();models=load_models(root);fingerprint=contract_hash(models)
 if pd.Timestamp(date)>pd.Timestamp(now.date()):raise ValueError('Refuse future asof')
 if date not in sessions(date,date):print(date,'non-trading day, skip');return None
 out=root/'reports'/(date+'.json')
 if if_needed and out.exists():
  old=json.loads(out.read_text())
  if old.get('status')=='complete' and old.get('asof')==date and old.get('contract_sha256')==fingerprint:print(date,'already complete; no repeat settlement');return old
 q,e,source=load_history(root,date,raw_override);env=e.iloc[-1].to_dict();regime=env['regime']
 if not regime:raise ValueError('MA20 history insufficient')
 if env['all_n']<4000 or env['main_n']<2000:raise ValueError('Insufficient current-session market coverage')
 pools,_=compute_pools(q,date,environment=e);turn,turn_errors=fetch_turnover(pools['breakout'].code.tolist(),date,root/'cache');pools['breakout']=attach_turnover_to_breakout(pools['breakout'],q,turn,date);mods=score_modules(pools,models,regime);errors=[]
 for tag,m in mods.items():
  if m['coverage']<.95 and m['pool_count']>=5 and m.get('unscorable_reason')!='常数截面，按冻结规则不评分':errors.append(f"{tag}:评分覆盖{m['coverage']:.2%}不足95%，未评分股票保留缺失")
  if m['pool_count'] and m['score_valid']==0 and m.get('unscorable_reason')!='常数截面，按冻结规则不评分':errors.append(f'{tag}:基础池存在但全部评分不可用（缺失或常数截面），非正常零候选')
 if turn_errors:errors.append({'turnover_batch_errors':turn_errors})
 status='partial' if errors else 'complete';path=root/'paper/account.json';account=json.loads(path.read_text()) if path.exists() else fresh(next_session(date));end=min(pd.Timestamp(date)+pd.Timedelta(days=40),CAL.last_session);cal=sessions('2023-01-03',end.strftime('%Y-%m-%d'));pending=[d for d in cal if account['start_session']<=d<=date and (not account.get('last_processed') or d>account['last_processed'])]
 for d in pending:
  ix=cal.index(d);prev=cal[ix-1] if ix else None;p=root/'reports'/(prev+'.json') if prev else None;previous=json.loads(p.read_text()) if p and p.exists() else None;account=settle(account,d,q,previous,cal)
 atomic_json(path,account)
 for name in ['trades','equity','decisions']:pd.DataFrame(account[name]).to_csv(root/'paper'/(name+'.csv'),index=False)
 report={'schema':1,'strategy':'DCEGHABF','asof':date,'status':status,'generated_at':now.isoformat(timespec='seconds'),'contract_sha256':fingerprint,'next_session':next_session(date),'environment':{k:(int(v) if k in ['all_n','main_n'] else (float(v) if k not in ['date','regime'] else v)) for k,v in env.items()},'modules':mods,'errors':errors,'source':source,'paper':{'start_session':account['start_session'],'last_processed':account['last_processed'],'cash':account['cash'],'holdings':account['holdings']},'sizing':{'initial_cash':200000,'fixed_entry_budget_including_fee':20000,'max_simultaneous_entry_cost':200000,'max_new_daily':1,'fee_each_side':.0003}}
 atomic_json(out,report);atomic_json(root/'reports/latest.json',report);text=markdown(report);(root/'reports'/(date+'.md')).write_text(text);(root/'reports/latest.md').write_text(text);print(text,flush=True);return report

def main():
 p=argparse.ArgumentParser();p.add_argument('--asof');p.add_argument('--if-needed',action='store_true');p.add_argument('--raw-cache');a=p.parse_args()
 try:
  r=scan(asof=a.asof,if_needed=a.if_needed,raw_override=a.raw_cache)
  if r and r['status']!='complete':raise SystemExit(2)
 except Exception as ex:
  now=datetime.now(ZoneInfo('Asia/Shanghai'));d=a.asof or now.date().isoformat();error={'asof':d,'status':'error','generated_at':now.isoformat(),'errors':[str(ex)],'modules':{}};atomic_json(ROOT/'reports'/(d+'.error.json'),error);atomic_json(ROOT/'reports/latest.json',error);(ROOT/'reports/latest.md').write_text(f'# DCEGHABF｜{d}\n\n本次数据/计算失败：{ex}\n\n未使用旧行情冒充当日候选。\n');traceback.print_exc();raise SystemExit(1)
if __name__=='__main__':main()
