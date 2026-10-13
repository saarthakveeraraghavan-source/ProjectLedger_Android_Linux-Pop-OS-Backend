# Changes in 0.2.0

- Create a project without a budget; add or remove its budget later. Existing budgets retain their values.
- Category suggestions are optional. AI can propose a new category and factual description; users can edit both. A new category becomes shared only when its reviewed expense is committed.
- Saves and AI descriptions request immediate automatic synchronization. The open app retries every 30 seconds, with durable WorkManager background/reconnection work. Existing preferences are respected.
- Finance answers show readable amounts, transaction details, and scope instead of raw JSON/UUID arrays. Largest-expense questions cover all history unless a period is requested; refunds and reversed entries are excluded.
- Empty/oversized questions cannot be submitted. Validation errors identify the field without exposing its input.
- Expense dates have a calendar picker and retain typed entry.
- Local inference uses inlined schemas and explicit JSON data instructions. Confirmation and exact financial validation remain mandatory.

Verified: 54 backend tests, 10 Android unit tests, 4 native phone checks, seven actual local-model extraction cases, live new-category/largest-expense API tests, signed release/lint, encrypted backup/restore, and deployment data preservation. See [VERIFICATION.md](VERIFICATION.md). Full physical failure drills remain documented separately.
