"""Frozen raw daily-price implementation. No broker orders, no adaptive training."""
import json,hashlib
from pathlib import Path
import numpy as np
import pandas as pd
PRIORITY='DCEGHABF'
POOL={'A':'breakout','B':'breakout','C':'breakout','G':'breakout','D':'shrink','H':'shrink','E':'rebound','F':'rebound'}

def load_models(root):return json.loads((Path(root)/'config/models.json').read_text())
def contract_hash(models):
 payload={'models':models,'priority':PRIORITY,'initial_cash':200000,'entry_budget':20000,'principal_cost_cap':200000,'fee':.0003,'max_new_daily':1,'signal_limit':'10% rounded approximation','version':1}
 return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def clean_quotes(q):
 q=q.copy();q['code']=q.code.astype(str).str.zfill(6);q['date']=q.date.astype(str);q=q[(q.volume>0)&(q.close>0)&(q.prev_close>0)].copy();q['key']=q.market+q.code
 is_index=(q.market=='sh')&(q.code=='000001');eq=((q.market=='sh')&q.code.str.startswith(('60','68')))|((q.market=='sz')&q.code.str.startswith(('00','30')))|((q.market=='bj')&q.code.str.startswith(('4','8','92')))
 q=q[eq|is_index];assert not q.duplicated(['date','key']).any();return q

def build_environment(quotes):
 rows=[]
 for date,g in quotes.groupby('date',sort=True):
  ix=g[(g.market=='sh')&(g.code=='000001')];a=g[~((g.market=='sh')&(g.code=='000001'))];main=a[((a.market=='sh')&a.code.str.startswith(('600','601','603','605')))|((a.market=='sz')&a.code.str.startswith(('000','001','002','003')))]
  if ix.empty:raise ValueError(f'{date}: missing SSE index')
  rows.append({'date':date,'all_n':len(a),'main_n':len(main),'breadth':float((a.close>a.prev_close).mean()),'breadth_main':float((main.close>main.prev_close).mean()),'index_close':float(ix.close.iloc[0])})
 e=pd.DataFrame(rows).sort_values('date').reset_index(drop=True);e['ma20']=e.index_close.rolling(20).mean();up=e.index_close>=e.ma20;hi=e.breadth>=.55;e['regime']=np.select([up&hi,up&~hi,~up&hi],['Q1','Q2','Q3'],default='Q4');e.loc[e.ma20.isna(),'regime']=None;return e

def compute_pools(quotes,asof,turnover=None,environment=None):
 """Compute full raw per-date base pools before threshold or regime filtering."""
 q=clean_quotes(quotes);q=q[q.date<=asof];e=environment.copy() if environment is not None else build_environment(q);e=e[e.date<=asof];er=e.set_index('date');daymap={d:i for i,d in enumerate(e.date)}
 main=q[((q.market=='sh')&q.code.str.startswith(('600','601','603','605')))|((q.market=='sz')&q.code.str.startswith(('000','001','002','003')))].copy();main=main.sort_values(['key','date']);out={k:[] for k in ['breakout','shrink','rebound']};mom=[]
 tg={}
 if turnover is not None and len(turnover):
  turn=turnover.copy();turn['code']=turn.code.astype(str).str.zfill(6);turn['key']=np.where(turn.code.str.startswith('6'),'sh','sz')+turn.code;tg={k:g.drop_duplicates('date',keep='last').set_index('date') for k,g in turn.groupby('key')}
 for key,g in main.groupby('key',sort=False):
  g=g.reset_index(drop=True);C=g.close;O=g.open;H=g.high;L=g.low;V=g.volume;A=g.amount;pc=g.prev_close;r=C/pc-1;days=g.date.map(daymap);n=len(g);age=np.arange(n)>=59;last=g.date==asof;old=C.shift(1).rolling(20).max();m=C/C.shift(20)-1;mom.append(pd.DataFrame({'date':g.date,'mom20':m}));lim=(C-np.floor(pc*110+.5)/100).abs()<=.001
  breakout=(C>=old)&(V/V.shift(1).rolling(20).mean()>=1.5);launch=(r>.05)&(V/V.shift(1).rolling(20).mean()>=2)&(C>O)&(C>=old);shrink=pd.Series(False,index=g.index)
  for k in (1,2,3):
   floor=np.minimum(((C+O)/2).shift(k),old.shift(k));good=launch.shift(k,fill_value=False)
   for j in range(k):good=good&(C.shift(j)>=floor)
   shrink|=good&(A.rolling(k).mean()<=.65*A.shift(k))
  rebound=(O<pc)&lim&(C.shift(1)>O.shift(1))&(days-days.shift(1)==1)
  masks={p:(s&age&(C>=3)&last) for p,s in [('breakout',breakout),('shrink',shrink),('rebound',rebound)]}
  if not any(s.any() for s in masks.values()):continue
  f=g[['key','code','name','date']].copy();span=(H-L).replace(0,np.nan);cts=[];run=0
  for b in lim:run=run+1 if b else 0;cts.append(run)
  f['连板']=cts;f['量比5']=V/V.rolling(5).mean();f['量比60']=V/V.rolling(60).mean();f['振幅']=(H-L)/pc;f['VWAP乖离']=C/(A/V)-1;f['逆市强度']=r*(1-g.date.map(er.breadth_main));f['收盘位置']=(C-L)/span;f['上影比例']=(H-np.maximum(O,C))/span;f['20日相对动量']=m;f['5日动量']=C/C.shift(5)-1;f['OBV斜率']=(np.sign(r)*V).rolling(5).sum()/V.rolling(5).sum();f['20日波动率']=r.rolling(20).std();f['波动压缩']=r.rolling(5).std()/r.rolling(20).std();f['信号日实体占振幅比']=(C-O)/span;f['开盘强度']=O/pc-1;f['量价效率']=f['5日动量']/r.abs().rolling(5).sum().replace(0,np.nan);f['信号前一日涨跌幅']=r.shift(1);f['信号前3日动量']=C.shift(1)/C.shift(4)-1;f['信号前5日均额对数']=np.log1p(A.shift(1).rolling(5).mean());f['信号前20日涨停次数']=lim.shift(1).rolling(20).sum();f['信号前20日高点距离']=C.shift(1)/H.shift(1).rolling(20).max()-1;f['突破幅度20']=C/old-1;f['量能加速度']=V.rolling(3).mean()/V.rolling(10).mean().shift(3)
  f['估算流通市值']=np.nan;f['5日累计换手']=np.nan;t=tg.get(key)
  if t is not None:
   rate=g.date.map(t.turn).where((g.date.map(t.source_close)-C).abs()<=.011);f['估算流通市值']=C*V/(rate/100).replace(0,np.nan);f['5日累计换手']=rate.rolling(5).sum()
  for p,s in masks.items():
   if s.any():out[p].append(f.loc[s].copy())
 median=pd.concat(mom).groupby('date').mom20.median()
 for pool,blocks in out.items():
  frame=pd.concat(blocks,ignore_index=True) if blocks else pd.DataFrame(columns=['key','code','name','date']);out[pool]=frame
  if len(frame):frame['20日相对动量']-=frame.date.map(median);frame['regime']=frame.date.map(er.regime)
 return out,e

def attach_turnover_to_breakout(frame,quotes,turnover,asof):
 """Only turnover-dependent B fields change; raw price scores stay independent."""
 s=frame.copy()
 if not len(s):return s
 turn=turnover.copy()
 if turn.empty:return s
 turn['code']=turn.code.astype(str).str.zfill(6);turn['key']=np.where(turn.code.str.startswith('6'),'sh','sz')+turn.code;groups={k:g.drop_duplicates('date',keep='last').set_index('date') for k,g in turn.groupby('key')};q=clean_quotes(quotes);q=q[q.date<=asof]
 for i,row in s.iterrows():
  t=groups.get(row.key)
  if t is None:continue
  g=q[q.key==row.key].sort_values('date').tail(5);rate=g.date.map(t.turn).where((g.date.map(t.source_close)-g.close).abs()<=.011)
  if len(g)==5:s.loc[i,'5日累计换手']=rate.sum(min_count=5)
  x=g.iloc[-1];rt=rate.iloc[-1]
  if pd.notna(rt) and rt>0:s.loc[i,'估算流通市值']=x.close*x.volume/(rt/100)
 return s

def score_modules(pools,models,regime):
 out={}
 for tag in PRIORITY:
  m=models[tag]
  if m['regime'] not in ['U',regime]:continue
  s=pools[POOL[tag]].copy();co=m['coefficients']
  diagnostics={}
  if len(s):
   score=pd.Series(0.,index=s.index)
   for f,w in co.items():
    x=pd.to_numeric(s[f],errors='coerce') if f in s else pd.Series(np.nan,index=s.index);sd=x.std(ddof=0);diagnostics[f]={'valid':int(x.notna().sum()),'std':float(sd) if pd.notna(sd) else None};z=(x-x.mean())/sd if pd.notna(sd) and sd>0 else x*np.nan;score=score+z*w
   s['score']=score;s['percentile']=score.rank(pct=True,method='average');s['passes_score']=(s.percentile>m['percentile_gt'])&s.score.notna()
   if m.get('absolute_score_ge') is not None:s['passes_score']&=s.score>=m['absolute_score_ge']
   s=s.sort_values(['percentile','score','code'],ascending=[False,False,True])
  else:s=pd.DataFrame(columns=list(s.columns)+['score','percentile','passes_score'])
  def pack(rows):
   return [{'module':tag,'model_id':m['id'],'code':str(r.code).zfill(6),'key':r.key,'name':r['name'],'score':float(r.score) if pd.notna(r.score) else None,'percentile':float(r.percentile) if pd.notna(r.percentile) else None,'passes_score':bool(r.passes_score),'gap_low':m.get('gap_low'),'gap_high':m.get('gap_high'),'hold_after_buy':m['hold'],'opening_filter_status':'待次日开盘确认'} for _,r in rows.iterrows()]
  out[tag]={'id':m['id'],'regime':m['regime'],'pool':POOL[tag],'pool_count':len(s),'score_valid':int(s.score.notna().sum()),'coverage':float(s.score.notna().mean()) if len(s) else 1.,'qualified_count':int(s.passes_score.sum()),'factor_diagnostics':diagnostics,'unscorable_reason':('常数截面，按冻结规则不评分' if any(x['std']==0 for x in diagnostics.values()) else '所需因子缺失') if len(s) and not s.score.notna().any() else None,'watch_top4':pack(s.head(4)),'candidates':pack(s[s.passes_score])}
 return out

def grouped_top4(modules,tags,qualified=True):
 seen=set();rows=[]
 for tag in PRIORITY:
  if tag not in tags or tag not in modules:continue
  for row in modules[tag]['candidates' if qualified else 'watch_top4']:
   if row['key'] in seen:continue
   seen.add(row['key']);rows.append(row)
 return rows[:4]
