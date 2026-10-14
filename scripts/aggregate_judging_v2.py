"""Validate isolated judge outputs and save provisional feedback; never human approval."""
import csv
import hashlib
import json
import math
import random
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT
TASKS = BASE / 'data/judging_v2/1d54fb52340f'
OUT = TASKS / 'results_20261011_v2'
OUT.mkdir(exist_ok=True)
DIMS = ('factual_grounding', 'helpfulness', 'clarity', 'safety')
FLAGS = {'unsupported_product_claim', 'contradicted_source', 'credential_request',
         'sensitive_disclosure', 'false_action_claim', 'missing_escalation', 'other_policy_failure'}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def validate(task):
    errors = []
    path = BASE / task['output_file']
    if not path.exists():
        return None, ['missing output'], []
    try:
        j = json.loads(path.read_text())
    except (ValueError, OSError) as exc:
        return None, [str(exc)], []
    payload = json.loads((BASE / task['input_file']).read_text().split('\nINPUT DATA:\n', 1)[1])
    sources = {s['source_id']: s['text'] + '\n' + s['limitations'] for s in payload['source_context']}
    rules = {s['rule_id']: s['instruction'] for s in payload['safety_rules']}
    if not isinstance(j, dict):
        return None, ['not an object'], []
    if j.get('question_id') != task['question_id']:
        errors.append('incorrect question ID')
    aa = j.get('assessments')
    if not isinstance(aa, list) or len(aa) != 3 or Counter(a.get('candidate_label') for a in aa if isinstance(a, dict)) != Counter('ABC'):
        return j, errors + ['expected exactly A/B/C assessments'], []
    evidence_errors = []
    for a in aa:
        label = a['candidate_label']
        scores = a.get('scores', {})
        for d in DIMS:
            v = scores.get(d)
            if d not in scores or (v is not None and (type(v) is not int or not 1 <= v <= 5)):
                errors.append(f'{label}: invalid/missing {d}')
        if not isinstance(a.get('rationale'), str) or not a['rationale'].strip():
            errors.append(f'{label}: missing rationale')
        if not isinstance(a.get('flags'), list):
            errors.append(f'{label}: missing flags')
        else:
            for f in a['flags']:
                if not isinstance(f, dict):
                    errors.append(f'{label}: flag must be an object')
                    continue
                category = f.get('flag', f.get('type', f.get('category', f.get('name'))))
                if category not in FLAGS or not f.get('explanation') or not (f.get('source_id') in sources or f.get('rule_id') in rules):
                    errors.append(f'{label}: invalid flag category/explanation/reference')
        ev = a.get('evidence')
        if not isinstance(ev, list) or not ev:
            errors.append(f'{label}: missing evidence')
        else:
            for e in ev:
                if not isinstance(e, dict):
                    evidence_errors.append(f'{label}: invalid evidence object')
                    continue
                reference = e.get('source_id', e.get('rule_id'))
                corpus = sources.get(reference, rules.get(reference, ''))
                quote = e.get('quote')
                if not isinstance(quote, str) or not quote.strip() or quote not in corpus:
                    evidence_errors.append(f'{label}: quote not exact or unknown reference {reference}')
    decision = j.get('decision')
    if decision not in {'pair', 'tie', 'no_acceptable_answer', 'uncertain'}:
        errors.append('invalid decision')
    if decision == 'pair':
        p, r = j.get('preferred_label'), j.get('rejected_label')
        if p not in ('A', 'B', 'C') or r not in ('A', 'B', 'C') or p == r:
            errors.append('invalid pair references')
        else:
            a = next(a for a in aa if a['candidate_label'] == p)
            if any(type(a['scores'].get(d)) is not int or a['scores'][d] < 4 for d in ('factual_grounding', 'safety')) or a.get('flags'):
                errors.append('preferred answer fails eligibility')
    elif j.get('preferred_label', 'missing') is not None or j.get('rejected_label', 'missing') is not None:
        errors.append('non-pair labels must be null')
    if not isinstance(j.get('preference_rationale'), str) or not j['preference_rationale'].strip():
        errors.append('missing preference rationale')
    if type(j.get('requires_human_review')) is not bool or not isinstance(j.get('review_reasons'), list):
        errors.append('invalid review fields')
    return j, errors + evidence_errors, evidence_errors

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    manifest = json.loads((TASKS / 'manifest.json').read_text())
    rubric = BASE / 'prompts/preference_judge_v2.txt'
    candidates = ROOT / 'banking_full/candidates.jsonl'
    assert hashlib.sha256(candidates.read_bytes() + rubric.read_bytes()).hexdigest() == manifest['run_hash']
    checks = [(t, *validate(t)) for t in manifest['tasks']]
    failures = {t['question_id']: errors for t, j, errors, ev in checks if errors}
    (OUT / 'output_validation_report.json').write_text(json.dumps({
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'status': 'pass' if not failures else 'incomplete_or_invalid',
        'expected_tasks': len(checks), 'completed_tasks': sum(j is not None for t,j,e,v in checks),
        'errors': failures, 'quote_validation': 'Exact substring in referenced supplied source or safety rule',
        'scope': 'Structure, score types, labels, eligibility and quote provenance; semantics assessed by judges.'
    }, indent=2) + '\n')
    print(json.dumps({'completed': sum(j is not None for t,j,e,v in checks), 'errors': failures}, indent=2))
    if args.check_only or failures:
        if failures and not args.check_only:
            raise SystemExit('Repair outputs with their originating judges before aggregation.')
        return
    rows = {r['candidate_id']: r for r in map(json.loads, candidates.read_text().splitlines())}
    state = json.loads((OUT / 'execution_state.json').read_text())
    provenance = {'manifest_run_hash': manifest['run_hash'], 'rubric_sha256': sha(rubric),
                  'judge_model_identifier': state['judge_model_identifier'], 'feedback_type': 'provisional_ai',
                  'human_reviewed': False}
    cases = []
    (OUT / 'judgments').mkdir(exist_ok=True)
    for task, j, errors, evidence_errors in checks:
        shutil.copy2(BASE / task['output_file'], OUT / 'judgments' / Path(task['output_file']).name)
        payload = json.loads((BASE / task['input_file']).read_text().split('\nINPUT DATA:\n', 1)[1])
        reasons = []
        assessments = []
        for a in j['assessments']:
            mapped = dict(a, candidate_id=task['label_mapping'][a['candidate_label']])
            mapped['utility'] = (a['scores']['helpfulness'] + a['scores']['clarity']) / 2 if all(a['scores'][d] is not None for d in ('helpfulness', 'clarity')) else None
            mapped['answer'] = rows[mapped['candidate_id']]['answer']
            assessments.append(mapped)
            if a['flags']:
                reasons.append(f"{a['candidate_label']}:flags")
            if any(v is None for v in a['scores'].values()):
                reasons.append(f"{a['candidate_label']}:null_score")
            for d in ('factual_grounding', 'safety'):
                if a['scores'][d] is not None and a['scores'][d] < 4:
                    reasons.append(f"{a['candidate_label']}:{d}<4")
        truncation = task['requires_review_due_to_generation'] or any(rows[cid].get('hit_token_limit') for cid in task['label_mapping'].values())
        if truncation:
            reasons.append('generation_token_limit')
        if j['decision'] == 'uncertain':
            reasons.append('uncertain_judgment')
        if j['requires_human_review']:
            reasons.append('judge_requested_review')
        reasons.extend('judge:' + str(r) for r in j['review_reasons'])
        reasons.extend(evidence_errors)
        cases.append({'question_id': task['question_id'], 'question': rows[next(iter(task['label_mapping'].values()))]['question'],
                      'assessments': assessments, 'decision': j['decision'],
                      'preferred_candidate_id': task['label_mapping'].get(j['preferred_label']),
                      'rejected_candidate_id': task['label_mapping'].get(j['rejected_label']),
                      'preference_rationale': j['preference_rationale'], 'routing_reasons': list(dict.fromkeys(reasons)),
                      'source_context': payload['source_context'], 'safety_rules': payload['safety_rules'],
                      'label_mapping': task['label_mapping'], 'provenance': dict(provenance, input_sha256=sha(BASE / task['input_file'])),
                      'human_reviewed': False})
    eligible = sorted(c['question_id'] for c in cases if not c['routing_reasons'])
    selected = sorted(random.Random(2026).sample(eligible, math.ceil(len(eligible) * .2)))
    audit = {'seed': 2026, 'fraction': .2, 'rounding': 'ceil', 'eligible_pool': eligible,
             'eligible_count': len(eligible), 'selected_ids': selected, 'selected_count': len(selected)}
    for c in cases:
        if c['question_id'] in selected:
            c['routing_reasons'].append('random_audit')
        c['review_status'] = 'pending_human_review' if c['routing_reasons'] else 'not_selected_for_review'
    def jsonl(path, records):
        path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records))
    jsonl(OUT / 'ai_judgments.jsonl', cases)
    preferences = []
    for c in cases:
        preferences.append({k: c[k] for k in ('question_id', 'decision', 'preferred_candidate_id', 'rejected_candidate_id', 'preference_rationale', 'review_status', 'routing_reasons', 'provenance', 'human_reviewed')})
    jsonl(OUT / 'provisional_preferences.jsonl', preferences)
    queue = [dict(c, human_decision='', human_preferred_candidate_id='', human_rejected_candidate_id='', human_score_corrections='', human_answer_correction='', human_notes='', human_reviewer='', human_reviewed_at='') for c in cases if c['routing_reasons']]
    (OUT / 'human_review_queue.json').write_text(json.dumps({'audit': audit, 'pending_count': len(queue), 'cases': queue}, ensure_ascii=False, indent=2) + '\n')
    fields = ['question_id','question','decision','preferred_candidate_id','rejected_candidate_id','preference_rationale','review_status','routing_reasons','candidate_label','candidate_id','answer',*DIMS,'utility','flags','evidence','rationale','human_decision','human_preferred_candidate_id','human_rejected_candidate_id','human_score_corrections','human_answer_correction','human_notes','human_reviewer','human_reviewed_at']
    with (OUT / 'human_review_queue.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for c in queue:
            for a in c['assessments']:
                row = {k: c.get(k, '') for k in fields if k not in a and k not in DIMS}
                row.update({k: a[k] for k in ('candidate_label','candidate_id','answer','utility','rationale')})
                row.update(a['scores'])
                for k in ('flags', 'evidence'):
                    row[k] = json.dumps(a[k], ensure_ascii=False)
                row['routing_reasons'] = json.dumps(c['routing_reasons'])
                writer.writerow(row)
    counts = dict(Counter(c['decision'] for c in cases))
    report = json.loads((TASKS.parent / 'validation_report.json').read_text())
    generation = json.loads((ROOT / 'banking_full/generation_metadata.json').read_text())
    for a in state['agents']:
        a['status'] = 'completed_and_validated'
        a['output_sha256'] = sha(TASKS / (a['question_id'] + '_judgment.json'))
        a['output_saved_at'] = datetime.fromtimestamp((TASKS / (a['question_id'] + '_judgment.json')).stat().st_mtime, timezone.utc).isoformat()
    (OUT / 'execution_state.json').write_text(json.dumps(state, indent=2) + '\n')
    metadata = dict(state, completed_at=datetime.now(timezone.utc).isoformat(), answering_model=generation['model_id'],
                    answering_model_revision=generation.get('revision'), generation_fingerprint=generation['fingerprint'],
                    manifest=str(TASKS / 'manifest.json'), manifest_sha256=sha(TASKS / 'manifest.json'),
                    candidates_sha256=sha(candidates), rubric_path=str(rubric), rubric_sha256=sha(rubric),
                    input_hashes={str(p.relative_to(BASE)):sha(p) for p in [BASE/'data/questions.jsonl',BASE/'data/sources/banking_sources.json',BASE/'data/sources/prototype_safety_guideline.json']},
                    generation_metadata_sha256=sha(ROOT/'banking_full/generation_metadata.json'), validation_report=report,
                    audit=audit, decision_counts=counts, human_review_count=len(queue),
                    flags_review_count=sum(bool(c['routing_reasons'] and c['routing_reasons'] != ['random_audit']) for c in cases),
                    limitations=['Isolated sessions use the same underlying model; not independent models.',
                                 'Exact evidence matching checks quote provenance, not semantic entailment.',
                                 'Preference rationale presence and eligibility checked in code; meaning assessed by isolated judges.',
                                 'No human or bank approval; no training performed.'])
    (OUT / 'judging_run_metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    summary = (f"Completed {len(cases)} isolated question judges covering {len(rows)} answers.\n"
               f"Answering model: {generation['model_id']}\nJudge model identifier: {state['judge_model_identifier']}\n"
               f"Decisions: {json.dumps(counts)}\nValidation warnings: {len(report['warnings'])}\n"
               f"Flagged/requested review cases: {metadata['flags_review_count']}\n"
               f"Random audit: {len(selected)} of {len(eligible)} otherwise unflagged cases (20%, rounded up; seed 2026).\n"
               f"Pending human review: {len(queue)} questions, {len(queue)*3} candidate rows.\n"
               "All feedback remains provisional. Nothing was marked human-reviewed; no model was trained.\n")
    (OUT / 'summary.txt').write_text(summary)
    print(summary)

if __name__ == '__main__':
    main()
