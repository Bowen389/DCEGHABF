import json
from pathlib import Path
import pandas as pd
import numpy as np
from src.engine import load_models,score_modules,grouped_top4
from src.paper import fresh,settle
ROOT=Path(__file__).resolve().parents[1]
CAL=['2026-11-20','2026-11-23','2026-11-24','2026-11-25','2026-11-26','2026-11-27','2026-11-30']
def candidate(key='sh600001',module='A',hold=1,low=None,high=None):return {'module':module,'key':key,'code':key[2:],'name':'测试','model_id':'fixture','score':1.,'percentile':1.,'passes_score':True,'gap_low':low,'gap_high':high,'hold_after_buy':hold}
def quote(date,key='sh600001',price=10.):return {'date':date,'key':key,'open':price,'close':price,'prev_close':10.}
def previous(rows):return {'asof':'2026-11-20','status':'complete','modules':{'A':{'candidates':rows}}}
def test_fixed_entry_never_grows_with_cash():
 for cash in [200000.,1000000.]:
  a=fresh('2026-11-23');a['cash']=cash;q=pd.DataFrame([quote('2026-11-23')]);b=settle(a,'2026-11-23',q,previous([candidate()]),CAL);h=b['holdings'][0];assert h['shares']==1900;assert h['cost']<=20000

def test_open_cannot_spend_close_proceeds():
 a=fresh('2026-11-23');a['cash']=0;a['holdings']=[dict(candidate('sh600002'),buy_date='2026-11-20',buy_price=10.,shares=1900,cost=19005.7,target_exit='2026-11-23',last_close=10.,last_quote_date='2026-11-20')]
 q=pd.DataFrame([quote('2026-11-23'),quote('2026-11-23','sh600002')]);b=settle(a,'2026-11-23',q,previous([candidate()]),CAL);assert not b['holdings'];assert len(b['trades'])==1;assert b['cash']>0

def test_holding_and_idempotency():
 q=pd.DataFrame([quote(d) for d in CAL]);a=settle(fresh('2026-11-23'),'2026-11-23',q,previous([candidate(hold=4)]),CAL);assert a['holdings'][0]['target_exit']=='2026-11-27';assert settle(a,'2026-11-23',q,None,CAL)==a
 for date in ['2026-11-24','2026-11-25','2026-11-26']:a=settle(a,date,q,None,CAL);assert len(a['holdings'])==1
 a=settle(a,'2026-11-27',q,None,CAL);assert not a['holdings'];assert len(a['trades'])==1

def test_execution_uses_fifth_candidate_after_open_filters():
 rows=[candidate('sh'+str(600001+i),low=-.02,high=-.01) for i in range(5)];q=pd.DataFrame([quote('2026-11-23',r['key'],9.85 if i==4 else 10.) for i,r in enumerate(rows)]);a=settle(fresh('2026-11-23'),'2026-11-23',q,previous(rows),CAL);assert a['holdings'][0]['key']=='sh600005'

def test_percentiles_before_threshold_and_constant_missing():
 m=load_models(ROOT)
 for tag in m:m[tag]['regime']='Q2'
 m['A'].update(regime='U',coefficients={'x':1.},percentile_gt=.8,absolute_score_ge=None)
 s=pd.DataFrame({'key':['sh60000'+str(i) for i in range(5)],'code':['60000'+str(i) for i in range(5)],'name':['测试']*5,'x':[1.,2.,3.,4.,5.]});p={'breakout':s,'shrink':pd.DataFrame(),'rebound':pd.DataFrame()};r=score_modules(p,m,'Q1')['A'];assert r['qualified_count']==1;assert r['candidates'][0]['percentile']==1.
 s['x']=1.;r=score_modules(p,m,'Q1')['A'];assert r['score_valid']==0 and not r['candidates']
