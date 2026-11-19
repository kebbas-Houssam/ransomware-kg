# Benchmark

LLM `ollama:qwen2.5:7b` · run 2026-11-19 09:51 · modes: vector, sparql, hybrid, hybrid2, agent

A question is correct when every expected value appears in the answer; an answer
is cited when it cites a paper id or thesis page that was in its context.

## Original 15 (used for error analysis)

| Mode | Accuracy | Answers with citations | Avg latency (s) | Errors |
|---|---|---|---|---|
| vector | 27% (4/15) | 93% | 14.3 | 0 |
| sparql | 40% (6/15) | 7% | 12.6 | 0 |
| hybrid | 47% (7/15) | 87% | 24.5 | 0 |
| hybrid2 | 53% (8/15) | 80% | 30.9 | 0 |
| agent | 67% (10/15) | 60% | 6.6 | 0 |

| Type | vector | sparql | hybrid | hybrid2 | agent |
|---|---|---|---|---|---|
| comparison (3) | 33% | 33% | 67% | 33% | 67% |
| counting (4) | 0% | 50% | 25% | 50% | 75% |
| factual (5) | 20% | 60% | 40% | 60% | 40% |
| why (3) | 67% | 0% | 67% | 67% | 100% |

<details><summary>Per question (✓ correct · ✗ wrong · 📎 cites its context)</summary>

| Id | Type | Question | vector | sparql | hybrid | hybrid2 | agent |
|---|---|---|---|---|---|---|---|
| q01 | factual | What accuracy does Kebbas et al. (2025) report on the DeftPunk dataset? | ✗ 📎 | ✓ | ✗ 📎 | ✓ | ✗ |
| q02 | factual | Quelle précision (precision) rapporte DeftPunk (Wang et al., OSDI 2024) sur son dataset ? | ✓ 📎 | ✗ | ✓ 📎 | ✓ 📎 | ✓ |
| q03 | factual | Which platform does the detector of Brodzik et al. (2024) target, and how does it collect its data? | ✗ 📎 | ✓ | ✓ 📎 | ✓ 📎 | ✗ |
| q04 | factual | Quels modèles d'apprentissage utilisent Aljabri et al. (2024) ? | ✗ 📎 | ✓ | ✗ 📎 | ✗ 📎 | ✗ |
| q05 | factual | Where was UNVEIL published, and what true positive rate does it report? | ✗ 📎 | ✗ | ✗ 📎 | ✗ 📎 | ✓ 📎 |
| q06 | counting | How many papers in the review are surveys? | ✗ 📎 | ✗ | ✗ 📎 | ✗ | ✓ 📎 |
| q07 | counting | Combien d'articles de détection reposent sur une analyse statique ? | ✗ 📎 | ✗ | ✓ 📎 | ✗ 📎 | ✗ 📎 |
| q08 | counting | How many papers target the Windows platform? | ✗ | ✓ | ✗ | ✓ | ✓ |
| q09 | counting | Combien d'articles de la revue ont été publiés en 2025 ? | ✗ 📎 | ✓ | ✗ 📎 | ✓ 📎 | ✓ 📎 |
| q10 | comparison | On the DeftPunk dataset, which reports the higher precision, Kebbas et al. (2025) or DeftPunk, and by how much? | ✗ 📎 | ✓ 📎 | ✓ 📎 | ✓ 📎 | ✓ 📎 |
| q11 | comparison | Quel article de détection rapporte la meilleure accuracy, et quelle est sa valeur ? | ✗ 📎 | ✗ | ✗ 📎 | ✗ 📎 | ✓ 📎 |
| q12 | comparison | Among deep-learning (DL) papers, which one reports the highest accuracy? | ✓ 📎 | ✗ | ✓ 📎 | ✗ 📎 | ✗ |
| q13 | why | Why is the approach of Lee et al. (2025) described as counter-evasion? Which attacker technique does it target? | ✓ 📎 | ✗ | ✓ 📎 | ✓ 📎 | ✓ 📎 |
| q14 | why | Pourquoi l'approche de Kebbas et al. (2025) est-elle qualifiée d'hybride ? | ✗ 📎 | ✗ | ✗ | ✗ 📎 | ✓ 📎 |
| q15 | why | Why is the 96.18% accuracy of ERW-Radar not directly comparable with the other accuracies? | ✓ 📎 | ✗ | ✓ 📎 | ✓ 📎 | ✓ 📎 |

</details>

## Held-out 10 (never used for tuning)

| Mode | Accuracy | Answers with citations | Avg latency (s) | Errors |
|---|---|---|---|---|
| vector | 80% (8/10) | 100% | 15.2 | 0 |
| sparql | 40% (4/10) | 20% | 9.2 | 0 |
| hybrid | 80% (8/10) | 90% | 21.6 | 0 |
| hybrid2 | 90% (9/10) | 90% | 23.1 | 0 |
| agent | 30% (3/10) | 50% | 9.0 | 0 |

| Type | vector | sparql | hybrid | hybrid2 | agent |
|---|---|---|---|---|---|
| comparison (2) | 100% | 100% | 100% | 100% | 50% |
| count (2) | 0% | 0% | 0% | 50% | 50% |
| value (3) | 100% | 33% | 100% | 100% | 0% |
| why (3) | 100% | 33% | 100% | 100% | 33% |

<details><summary>Per question (✓ correct · ✗ wrong · 📎 cites its context)</summary>

| Id | Type | Question | vector | sparql | hybrid | hybrid2 | agent |
|---|---|---|---|---|---|---|---|
| h01 | value | What accuracy does Aljabri et al. (2024) report for memory-based ransomware detection? | ✓ 📎 | ✓ | ✓ 📎 | ✓ 📎 | ✗ |
| h02 | value | Quel F2-score obtient iCNN-LSTM+ ? | ✓ 📎 | ✗ | ✓ 📎 | ✓ 📎 | ✗ |
| h03 | value | What precision does Lee et al. (2025) report on FPE-encrypted files? | ✓ 📎 | ✗ | ✓ 📎 | ✓ 📎 | ✗ |
| h04 | count | Combien d'approches de détection utilisent une analyse statique ? | ✗ 📎 | ✗ | ✗ 📎 | ✓ 📎 | ✓ 📎 |
| h05 | count | How many detection papers were published in 2025? | ✗ 📎 | ✗ | ✗ | ✗ | ✗ 📎 |
| h06 | comparison | Which reports the higher accuracy: Scalas et al. (Android) or Maazalahi et al.? | ✓ 📎 | ✓ 📎 | ✓ 📎 | ✓ 📎 | ✗ |
| h07 | comparison | Sur le dataset DeftPunk, quel système a le meilleur recall : DeftPunk ou le modèle hybride de Kebbas ? | ✓ 📎 | ✓ | ✓ 📎 | ✓ 📎 | ✓ 📎 |
| h08 | why | Pourquoi les approches statiques sont-elles souvent reléguées à un rôle de premier filtre ? | ✓ 📎 | ✗ 📎 | ✓ 📎 | ✓ 📎 | ✗ |
| h09 | why | What does SRDC bring compared with classic API-sequence detectors? | ✓ 📎 | ✗ | ✓ 📎 | ✓ 📎 | ✗ 📎 |
| h10 | why | Why do Brodzik et al. run the detection inside the Linux kernel with eBPF? | ✓ 📎 | ✓ | ✓ 📎 | ✓ 📎 | ✓ 📎 |

</details>
