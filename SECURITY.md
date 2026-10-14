# Security Policy

**Do not open public issues for vulnerabilities.** Email the maintainers (see GitHub repo security tab) with:

- affected version (`prof version`), config, policy id
- reproduction (redact private keys), impact assessment

## Boundaries (v0.1)

- Agent/SDK is **untrusted**. Gateway verifies server-side.
- Demo keys are **ephemeral in-memory**. Production must provide `PROF_APPROVER_PRIV` or a KMS/HSM signer, TLS, and persistent ledger/nonce stores.
- Single-node ledger/nonce stores are crash-durable, **not** multi-node HA.
- Signatures prove permit integrity, not model-output correctness.

We aim to acknowledge reports within 72h and publish fixes with a CHANGELOG entry.
