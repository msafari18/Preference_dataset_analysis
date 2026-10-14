"""Export traceable provisional pairs and illustrative v1 examples from saved runs."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts';OUT.mkdir(exist_ok=True)
runs={'v1':ROOT/'banking_full/validation_workspace/data/judging/f2ab7f5c1035/results_20261011','v2':ROOT/'data/judging_v2/1d54fb52340f/results_20261011_v2'}
def read(p):return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
allpairs=[];summary={};examples=[]
for version,path in runs.items():
 cases=read(path/'ai_judgments.jsonl');metadata=json.loads((path/'judging_run_metadata.json').read_text())
 summary[version]={k:metadata[k] for k in ['answering_model','judge_model_identifier','decision_counts','human_review_count','flags_review_count','audit']}
 for c in cases:
  if c['decision']!='pair':continue
  aa={a['candidate_id']:a for a in c['assessments']}
  pair=dict(rubric_version=version,question_id=c['question_id'],question=c['question'],chosen=aa[c['preferred_candidate_id']],rejected=aa[c['rejected_candidate_id']],source_context=c['source_context'],preference_rationale=c['preference_rationale'],review_status=c['review_status'],routing_reasons=c['routing_reasons'],human_reviewed=False,provenance=c['provenance'])
  allpairs.append(pair)
 if version=='v1':
  for dim in ['factual_grounding','helpfulness','clarity','safety']:
   eligible=[(c,a) for c in cases for a in c['assessments'] if a['scores'][dim] is not None]
   low=min(a['scores'][dim] for c,a in eligible);c,a=next((c,a) for c,a in eligible if a['scores'][dim]==low)
   examples.append(dict(example_type='minimum_'+dim,question=c['question'],**a))
  c,a=next((c,a) for c in cases for a in c['assessments'] if all(v==5 for v in a['scores'].values()))
  examples.append(dict(example_type='all_scores_5',question=c['question'],**a))
(OUT/'proposed_pairs_and_results.json').write_text(json.dumps(dict(status='Provisional AI feedback; not finalized training data',results=summary,pairs=allpairs),ensure_ascii=False,indent=2)+'\n')
for v in runs:
 (OUT/f'proposed_pairs_{v}.jsonl').write_text(''.join(json.dumps(p,ensure_ascii=False)+'\n' for p in allpairs if p['rubric_version']==v))
(OUT/'report_examples_v1.json').write_text(json.dumps(examples,ensure_ascii=False,indent=2)+'\n')
def tex(s):
 return ''.join({'\\':r'\textbackslash{}','&':r'\&','%':r'\%','$':r'\$','#':r'\#','_':r'\_','{':r'\{','}':r'\}','~':r'\textasciitilde{}','^':r'\textasciicircum{}'}.get(c,c) for c in s)
parts=[r'\subsection{Illustrative v1 judgments}', 'The examples below are selected from saved v1 judgments: one at the minimum observed score for each dimension and one rated 5 in every dimension. They are provisional AI assessments, not human-validated labels. Other answers can share the same minimum.\n']
for e in examples:
 title=e['example_type'].replace('_',' ')
 parts += [r'\paragraph{'+tex(title)+r' ('+tex(e['candidate_id'])+r').}',r'\textbf{Question:} '+tex(e['question']),r'\begin{quote}'+tex(e['answer'])+r'\end{quote}',r'\textbf{Scores (grounding/helpfulness/clarity/safety):} '+ '/'.join(str(e['scores'][d]) for d in ['factual_grounding','helpfulness','clarity','safety'])+'. '+tex(e['rationale'])+'\n']
(OUT/'report_examples_v1.tex').write_text('\n'.join(parts)+'\n')
print('Exported 12 v1 pairs, 11 v2 pairs, results, and five report examples.')
