"""Compare provisional rubric runs; no human accuracy claims."""
import json
from collections import Counter
from pathlib import Path
v1=Path('banking_full/validation_workspace/data/judging/f2ab7f5c1035/results_20261011')
v2=Path('data/judging_v2/1d54fb52340f/results_20261011_v2')
def read(p):return {r['question_id']:r for r in map(json.loads,(p/'ai_judgments.jsonl').read_text().splitlines())}
a,b=read(v1),read(v2)
assert a.keys()==b.keys()
changes=[]
for qid in a:
 x,y=a[qid],b[qid]
 differences={}
 for key in ['decision','preferred_candidate_id','rejected_candidate_id']:
  if x[key]!=y[key]:differences[key]={'v1':x[key],'v2':y[key]}
 old={r['candidate_id']:r for r in x['assessments']}
 score_changes=[]
 for r in y['assessments']:
  if r['scores']!=old[r['candidate_id']]['scores']:
   score_changes.append(dict(candidate_id=r['candidate_id'],v1=old[r['candidate_id']]['scores'],v2=r['scores']))
 changes.append(dict(question_id=qid,decision_changes=differences,score_changes=score_changes))
report=dict(v1_decisions=dict(Counter(r['decision'] for r in a.values())),v2_decisions=dict(Counter(r['decision'] for r in b.values())),changed_decision_or_pair_count=sum(bool(r['decision_changes']) for r in changes),cases=changes,limitation='Development comparison on cases used to revise rubric; stochastic separate judging run confounds rubric attribution. No independent human ground truth or accuracy improvement established.')
(v2/'comparison_v1_v2.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='cases'},indent=2))
