# Benchmark

15 questions (FR/EN) · LLM `ollama:qwen2.5:7b` · run 2026-11-19 08:38

| Mode | Accuracy | Answers with citations | Avg latency (s) | Errors |
|---|---|---|---|---|
| vector | 27% (4/15) | 93% | 15.3 | 0 |
| sparql | 40% (6/15) | 7% | 11.7 | 0 |
| hybrid | 47% (7/15) | 87% | 25.5 | 0 |

## Accuracy by question type

| Type | vector | sparql | hybrid |
|---|---|---|---|
| comparison (3) | 33% | 33% | 67% |
| counting (4) | 0% | 50% | 25% |
| factual (5) | 20% | 60% | 40% |
| why (3) | 67% | 0% | 67% |

## Per question

✓ correct · ✗ wrong · 📎 cites its context

| Id | Type | Question | vector | sparql | hybrid |
|---|---|---|---|---|---|
| q01 | factual | What accuracy does Kebbas et al. (2025) report on the DeftPunk dataset? | ✗ 📎 | ✓ | ✗ 📎 |
| q02 | factual | Quelle précision (precision) rapporte DeftPunk (Wang et al., OSDI 2024) sur son dataset ? | ✓ 📎 | ✗ | ✓ 📎 |
| q03 | factual | Which platform does the detector of Brodzik et al. (2024) target, and how does it collect its data? | ✗ 📎 | ✓ | ✓ 📎 |
| q04 | factual | Quels modèles d'apprentissage utilisent Aljabri et al. (2024) ? | ✗ 📎 | ✓ | ✗ 📎 |
| q05 | factual | Where was UNVEIL published, and what true positive rate does it report? | ✗ 📎 | ✗ | ✗ 📎 |
| q06 | counting | How many papers in the review are surveys? | ✗ 📎 | ✗ | ✗ 📎 |
| q07 | counting | Combien d'articles de détection reposent sur une analyse statique ? | ✗ 📎 | ✗ | ✓ 📎 |
| q08 | counting | How many papers target the Windows platform? | ✗ | ✓ | ✗ |
| q09 | counting | Combien d'articles de la revue ont été publiés en 2025 ? | ✗ 📎 | ✓ | ✗ 📎 |
| q10 | comparison | On the DeftPunk dataset, which reports the higher precision, Kebbas et al. (2025) or DeftPunk, and by how much? | ✗ 📎 | ✓ 📎 | ✓ 📎 |
| q11 | comparison | Quel article de détection rapporte la meilleure accuracy, et quelle est sa valeur ? | ✗ 📎 | ✗ | ✗ 📎 |
| q12 | comparison | Among deep-learning (DL) papers, which one reports the highest accuracy? | ✓ 📎 | ✗ | ✓ 📎 |
| q13 | why | Why is the approach of Lee et al. (2025) described as counter-evasion? Which attacker technique does it target? | ✓ 📎 | ✗ | ✓ 📎 |
| q14 | why | Pourquoi l'approche de Kebbas et al. (2025) est-elle qualifiée d'hybride ? | ✗ 📎 | ✗ | ✗ |
| q15 | why | Why is the 96.18% accuracy of ERW-Radar not directly comparable with the other accuracies? | ✓ 📎 | ✗ | ✓ 📎 |
