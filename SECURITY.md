# Security

This is a small personal project, maintained on a best-effort basis.

To report a vulnerability, use GitHub's **Report a vulnerability** button on this repository's
Security tab (private reporting), rather than a public issue.

By design, harness-core never logs secrets: API keys are read from the environment, recorded
only by provider name, and kept out of the ledger and of object representations. Tests run
offline and fail on any real network or process call.
