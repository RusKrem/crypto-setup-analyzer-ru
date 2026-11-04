# Contributing

1. Create a feature branch.
2. Keep market-data access, scanning rules, UI, persistence, and Telegram delivery separated by responsibility.
3. Add or update unit tests for behaviour changes.
4. Run `python -m unittest discover -v` before submitting changes.
5. Never include `.env`, bot tokens, local databases, Telegram queue jobs, personal logs, or machine-specific paths.
6. Do not describe an alert as a profitable trade or a confirmed reversal guarantee.
