# Synthetic Banking App Feedback Dataset (PoV)

- Files:
  - `synthetic_banking_app_feedback_15000.csv` - primary dataset, 15,000 synthetic feedback records.
  - `synthetic_banking_app_feedback_1800.csv` - smaller fixture, 1,800 synthetic feedback records.
- Provenance: generated for software testing and proof-of-value development; not collected from real customers and not representative of any bank.
- Generation: produced deterministically by `scripts/generate_feedback_dataset.py` from `taxonomy/banking_taxonomy_v1.yaml`. Every one of the 62 active feature nodes in the taxonomy is represented. Re-run with `--rows`, `--seed`, `--min-per-node`, `--taxonomy` and `--out` to vary size or seed.
- Language: English (`en`) with a minority of Hinglish (`hinglish`) samples
- Time range: 2025-12-01 through 2026-11-30 (UTC)
- Sources represented: app-store reviews, in-app feedback, post-interaction surveys, complaint portal submissions and support-chat summaries.
- Themes represented in the text: UPI, IMPS/NEFT/RTGS transfers, OTP, login/biometrics, beneficiary management, bill payments, account/transaction history, statements, cards, deposits, loans, KYC/onboarding, performance, customer support/disputes, notifications and navigation.
- Includes positive, mixed and negative experiences, occasional multi-issue comments, varied phrasing, optional ratings, application versions and pseudonymous synthetic customer references.
- Includes intentional exact and near duplicates (same customer/date) to exercise deduplication, plus a small number of synthetic PII-like tails to exercise redaction.
- The CSV intentionally contains no model-generated topic or journey labels so it can be used as a raw-input test fixture for Modules A-E.

## Columns

`feedback_id`, `submitted_at`, `source_type`, `source_channel`, `platform`, `app_version`, `language`, `synthetic_customer_ref`, `rating_1_to_5`, `feedback_title`, `feedback_text`, `is_synthetic`.

All `synthetic_customer_ref` values are fictional identifiers. `is_synthetic` is `true` for every row.
