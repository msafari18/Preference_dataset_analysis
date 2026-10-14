# Banking preference-data prototype

Generate banking answers, judge them with isolated Codex agents, and prepare preference pairs for human review. **Fine-tuning is proposed, not implemented.**

## 1. Prepare questions

- Review `data/sources/banking_sources.json` and `prototype_safety_guideline.json` in the same folder.
- Use `prompts/question_generation.txt` in Codex to draft questions and paraphrases.
- Review the drafts and save them in `data/questions.jsonl`. Keep equivalent questions under one `question_family_id`.

The supplied set contains 10 original questions and 10 paraphrases.

## 2. Generate answers in Colab

Open `notebooks/generate_llama_candidates.ipynb` in Colab and select a T4 GPU.

1. Obtain Hugging Face access to `meta-llama/Llama-3.2-3B-Instruct` and authenticate through the hidden token prompt.
2. Upload `questions.jsonl`, `banking_sources.json`, and `prototype_safety_guideline.json`.
3. Set `INPUTS_REVIEWED = True`. Run with `SMOKE_TEST = True` first, then `False` for all 60 answers.
4. Download the ZIP and extract it as `banking_full/`.

The notebook includes structural validation and judge-input preparation. It does not run the judges. Keep tokens out of files and commits.

## 3. Validate and judge in Codex

From the repository root:

```bash
python3 scripts/prepare_judging.py --candidates banking_full/candidates.jsonl
```

If validation passes, paste this into an agent-enabled Codex session:

```text
Follow prompts/run_completed_judge_agents.txt for banking_full.
Use the manifest printed by my latest validation run.
Run one fresh judge agent per question, using its prepared input only.
Save judgments, aggregate results, and prepare the human-review queue.
Record the actual execution metadata; keep all labels provisional.
Do not train a model or mark anything human-reviewed.
```

The rubric is `prompts/preference_judge.txt`. Separate agents use isolated contexts, not necessarily different models. No external API key is required for this Codex workflow.

## 4. Human review

Open the generated `human_review_queue.json` or CSV. Review flagged cases and the random audit; record confirmations, corrections, ties, or exclusions. Optional reusable explanations can be skipped.

AI judging and file validation do not establish bank approval. Do not treat pending pairs as finalized training data.

## 5. Saved results and report

- `artifacts/proposed_pairs_v1.jsonl`: 12 proposed pairs from the reported run.
- `artifacts/report_examples_v1.json`: saved examples and original judge scores.
- `banking_full/validation_workspace/data/judging/`: archived judgments, metadata, and review queue.

To rebuild the report (requires LaTeX):

```bash
pdflatex literature_review.tex
pdflatex literature_review.tex
```

`scripts/aggregate_completed_judging.py` and `scripts/export_report_artifacts.py` target archived runs. For a new run, the Codex coordinator must use its new manifest and actual execution state, adapting aggregation paths. The exporter overwrites generated report examples; preserve manual edits before running it.

Sources are public-page summaries and questions are fictional. The workflow is AI-assisted research material. Repeated model runs may differ; saved judgments reproduce the reported results.
