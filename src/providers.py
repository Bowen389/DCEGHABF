"""Public raw daily bars, compact per-stock history and independently validated turnover."""
from pathlib import Path
from collections import deque
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import hashlib,json,pickle,gzip,urllib.request,urllib.error,time
import pandas as pd
import exchange_calendars as xcals
from .tdx_parser import _tdx_parse_package
from .engine import clean_quotes
CAL=xcals.get_calendar('XSHG')

def sessions(start,end):return [x.strftime('%Y-%m-%d') for x in CAL.sessions_in_range(pd.Timestamp(start),pd.Timestamp(end))]
def next_session(date):return CAL.next_session(pd.Timestamp(date)).strftime('%Y-%m-%d')
def last_session(date):return CAL.date_to_session(pd.Timestamp(date),direction='previous').strftime('%Y-%m-%d')
def atomic_json(path,data):
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False));tmp.replace(p)
def get_bytes(url,attempts=3,timeout=25):
 error=None
 for n in range(attempts):
  try:
   with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 DCEGHABF daily research'}),timeout=timeout) as r:return r.read()
  except urllib.error.HTTPError as e:
   if e.code==404:raise
   error=e
  except Exception as e:error=e
  if n+1<attempts:time.sleep(min(1+n,3))
 raise error

def download_day(date,raw_dir):
 raw=Path(raw_dir);raw.mkdir(parents=True,exist_ok=True);p=raw/(date.replace('-','')+'.pkl.gz')
 if p.exists():return date,pd.read_pickle(p),{'source':'validated local raw cache','cache':p.name}
 url='https://www.tdx.com.cn/products/data/data/g4day/'+date.replace('-','')+'.zip';b=get_bytes(url);rows=_tdx_parse_package(b,date.replace('-',''),only_equities=True);q=clean_quotes(pd.DataFrame(rows));check=q[q.date==date];assert len(check)==len(q) and len(q)>4000,(date,'daily market coverage too small');assert ((q.market=='sh')&(q.code=='000001')).any();q.to_pickle(p,compression='gzip');return date,q,{'source':url,'source_zip_sha256':hashlib.sha256(b).hexdigest(),'rows':len(q)}

def load_history(root,asof,raw_override=None):
 """Keep the last 140 EFFECTIVE observations per stock, not a 140-calendar-day approximation."""
 root=Path(root);cache=root/'cache';cache.mkdir(exist_ok=True);file=cache/'compact.pkl.gz';raw=Path(raw_override) if raw_override else cache/'raw'
 if file.exists():
  with gzip.open(file,'rb') as f:state=pickle.load(f)
  if state.get('version')!=1:raise ValueError('Unknown history cache schema')
 else:state={'version':1,'rows':{},'environment':[],'sources':{}}
 if state['environment'] and state['environment'][-1]['date']>asof:raise ValueError('Compact cache is ahead of requested asof; use a clean cache for historical replay')
 existing={x['date'] for x in state['environment']};needed=[d for d in sessions('2023-01-03',asof) if d not in existing];received={};fail=[]
 def fetch(d):
  try:return download_day(d,raw)
  except Exception as ex:return d,None,{'error':str(ex)[:300]}
 with ThreadPoolExecutor(max_workers=12) as ex:
  for d,q,meta in ex.map(fetch,needed):
   if q is None:fail.append({'date':d,**meta});continue
   received[d]=meta
   if len(received)%50==0:print('downloaded',len(received),'/',len(needed),flush=True)
 # Historical holes cannot silently compress the exchange calendar.
 if fail:raise RuntimeError('Missing exchange-session archives: '+json.dumps(fail[:8],ensure_ascii=False))
 cols=['date','market','code','name','prev_close','open','high','low','close','volume','amount']
 hist={k:deque(v,maxlen=140) for k,v in state['rows'].items()}
 for d in sorted(received):
  meta=received[d];q=clean_quotes(pd.read_pickle(raw/(d.replace('-','')+'.pkl.gz')));idx=(q.market=='sh')&(q.code=='000001');a=q[~idx];main=a[((a.market=='sh')&a.code.str.startswith(('600','601','603','605')))|((a.market=='sz')&a.code.str.startswith(('000','001','002','003')))];assert len(main)>2000
  state['environment'].append({'date':d,'all_n':len(a),'main_n':len(main),'breadth':float((a.close>a.prev_close).mean()),'breadth_main':float((main.close>main.prev_close).mean()),'index_close':float(q.loc[idx,'close'].iloc[0])})
  for row in main[cols].itertuples(index=False,name=None):hist.setdefault(row[1]+row[2],deque(maxlen=140)).append(row)
  state['sources'][d]=meta
 state['rows']={k:list(v) for k,v in hist.items()};state['environment']=sorted(state['environment'],key=lambda x:x['date']);tmp=file.with_suffix('.tmp')
 if received or not file.exists():
  with gzip.open(tmp,'wb',compresslevel=1) as f:pickle.dump(state,f,protocol=5)
  tmp.replace(file)
 q=pd.DataFrame([r for rs in hist.values() for r in rs],columns=cols);q['key']=q.market+q.code;e=pd.DataFrame(state['environment']);e=e[e.date<=asof].sort_values('date').reset_index(drop=True);e['ma20']=e.index_close.rolling(20).mean();up=e.index_close>=e.ma20;hi=e.breadth>=.55
 import numpy as np
 e['regime']=np.select([up&hi,up&~hi,~up&hi],['Q1','Q2','Q3'],default='Q4');e.loc[e.ma20.isna(),'regime']=None
 if e.empty or e.date.iloc[-1]!=asof:raise ValueError('History does not reach requested session')
 return q,e,{'history_start':'2023-01-03','cache_version':1,'valid_observations_per_stock_cap':140,'market_source':state['sources'].get(asof),'session_count':len(e),'latest_all_n':int(e.iloc[-1].all_n)}

def fetch_turnover(codes,asof,cache_dir):
 """Same Sohu history source as frozen research. Failed stocks remain missing."""
 if not codes:return pd.DataFrame(columns=['code','date','turn','source_close']),[]
 start=(pd.Timestamp(asof)-pd.Timedelta(days=40)).strftime('%Y%m%d');end=asof.replace('-','');cache=Path(cache_dir)/'turnover'/asof;cache.mkdir(parents=True,exist_ok=True);codes=sorted(set(codes));batches=[codes[i:i+10] for i in range(0,len(codes),10)]
 def get(cs):
  p=cache/('_'.join(cs)+'.json');url='https://q.stock.sohu.com/hisHq?code='+','.join('cn_'+c for c in cs)+'&start='+start+'&end='+end+'&stat=1&order=D&period=d&rt=json'
  try:
   b=p.read_bytes() if p.exists() else get_bytes(url,attempts=3,timeout=30);z=json.loads(b.decode('gb18030'));assert isinstance(z,list);p.write_bytes(b);return cs,z,None
  except Exception as ex:return cs,[],str(ex)[:200]
 rows=[];errors=[]
 with ThreadPoolExecutor(max_workers=6) as ex:
  for cs,z,error in ex.map(get,batches):
   if error:errors.append({'codes':cs,'error':error})
   for item in z:
    for a in item.get('hq',[]):
     try:rows.append({'code':item['code'].removeprefix('cn_'),'date':a[0],'turn':float(a[9].removesuffix('%')),'source_close':float(a[2])})
     except (ValueError,IndexError,TypeError):continue
 return pd.DataFrame(rows,columns=['code','date','turn','source_close']).drop_duplicates(['code','date']),errors
