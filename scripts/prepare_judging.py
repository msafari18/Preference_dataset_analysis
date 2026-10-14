"""Validate candidate records and prepare isolated judge-agent inputs (no model calls)."""
import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidates', default='candidates.jsonl')
    parser.add_argument('--questions', default='data/questions.jsonl')
    parser.add_argument('--output', default='data/judging')
    parser.add_argument('--rubric', default='prompts/preference_judge.txt')
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    errors, warnings = [], []
    def read_jsonl(path):
        records = []
        try:
            for line_no, line in enumerate(Path(path).read_text().splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise ValueError('record must be an object')
                    records.append(record)
                except (ValueError, TypeError) as exc:
                    errors.append(f'{path}:{line_no}: {exc}')
        except OSError as exc:
            errors.append(str(exc))
        return records
    questions = read_jsonl(args.questions)
    candidates = read_jsonl(args.candidates)
    sources = {r['source_id']: r for r in json.loads(Path('data/sources/banking_sources.json').read_text())}
    safety = json.loads(Path('data/sources/prototype_safety_guideline.json').read_text())
    rubric = Path(args.rubric).read_text()
    qmap = {q.get('question_id'): q for q in questions}
    if len(qmap) != len(questions):
        errors.append('Duplicate question IDs')
    if not questions:
        errors.append('Question set is empty')
    groups = defaultdict(list)
    seen = set()
    for i, r in enumerate(candidates, 1):
        cid, qid = r.get('candidate_id'), r.get('question_id')
        required = ['candidate_id', 'question_id', 'question_family_id', 'question', 'source_ids', 'answer', 'model_id']
        if any(not r.get(k) for k in required):
            errors.append(f'Record {i}: missing/empty required field')
            continue
        if not isinstance(cid, str) or not isinstance(qid, str):
            errors.append(f'Record {i}: IDs must be strings')
            continue
        if cid in seen:
            errors.append(f'Duplicate candidate ID: {cid}')
        seen.add(cid)
        if qid not in qmap:
            errors.append(f'{cid}: unknown question ID')
            continue
        q = qmap[qid]
        for k in ['question', 'question_family_id', 'source_ids']:
            if r[k] != q[k]:
                errors.append(f'{cid}: {k} differs from question file')
        if not isinstance(r['source_ids'], list) or any(s not in sources for s in r['source_ids']):
            errors.append(f'{cid}: invalid source links')
        if not isinstance(r['answer'], str) or not r['answer'].strip():
            errors.append(f'{cid}: empty/non-text answer')
        if r.get('hit_token_limit'):
            warnings.append(f'{cid}: token limit reached; requires review for truncation')
        for k in ['model_revision', 'run_fingerprint', 'seed', 'generation_settings']:
            if k not in r:
                warnings.append(f'{cid}: missing provenance field {k}')
        groups[qid].append(r)
    for qid in qmap:
        if len(groups[qid]) != 3:
            errors.append(f'{qid}: expected 3 answers, found {len(groups[qid])}')
        texts = [r['answer'].strip() for r in groups[qid] if isinstance(r['answer'], str)]
        if len(texts) != len(set(texts)):
            warnings.append(f'{qid}: duplicate answers; allow ties, do not force a pair')
    report = dict(status='fail' if errors else 'pass', question_count=len(questions), candidate_count=len(candidates), errors=errors, warnings=warnings, scope='Structural validation only; does not establish factual correctness, safety, or preference quality.')
    (out/'validation_report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    if errors:
        raise SystemExit('Validation failed; no new judge tasks produced. Do not use old tasks.')
    run_hash = hashlib.sha256(Path(args.candidates).read_bytes()+rubric.encode()).hexdigest()
    tasks = out / run_hash[:12]
    tasks.mkdir(exist_ok=True)
    manifest = []
    for index, qid in enumerate(qmap):
        q = qmap[qid]
        rows = sorted(groups[qid], key=lambda r:r['candidate_id'])
        random.Random(2026+index).shuffle(rows)
        context = [{k:sources[s][k] for k in ['source_id','text','limitations']} for s in q['source_ids']]
        payload = dict(question_id=qid, question=q['question'], source_context=context,
            safety_rules=safety['rules'], candidates=[dict(candidate_label=chr(65+i),answer=r['answer']) for i,r in enumerate(rows)])
        path = tasks / f'{qid}_input.txt'
        path.write_text(rubric+'\nINPUT DATA:\n'+json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
        manifest.append(dict(question_id=qid,input_file=str(path),output_file=str(tasks/f'{qid}_judgment.json'),label_mapping={chr(65+i):r['candidate_id'] for i,r in enumerate(rows)},requires_review_due_to_generation=any(r.get('hit_token_limit') for r in rows),status='pending'))
    (tasks/'manifest.json').write_text(json.dumps(dict(run_hash=run_hash,tasks=manifest),indent=2)+'\n')
    print(f'Prepared {len(manifest)} agent tasks. Manifest: {tasks}/manifest.json')

if __name__ == '__main__':
    main()
