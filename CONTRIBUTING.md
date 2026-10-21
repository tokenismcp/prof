# Contributing to PROF

Thanks for considering a contribution. PROF grows on reproducible security, not hype.

## License of contributions

PROF is source-available (PolyForm Noncommercial 1.0.0) with a paid commercial
license. By submitting a contribution you confirm you wrote it (or may submit it),
you keep your copyright, and you grant 4Chains Inc. a perpetual, worldwide,
irrevocable right to distribute it under the project's noncommercial license and
under commercial licenses. Add `Signed-off-by:` (git commit -s) to each commit.

## Ground rules

1. **Fail-closed first.** Any ambiguous enforcement question resolves to deny + test.
2. **No absolute security claims.** Say what threat, what sample size, what environment.
3. **Small, reviewable PRs.** One enforcement change = one PR + tests + docs line.

## Dev setup (2 min)

```sh
pip install -e ".[dev]"
python -m pytest -q
python -m prof demo
```

## Where to contribute

- `prof/` — core enforcement (permit/policy/gateway/ledger). Needs tests for every branch.
- `examples/` — new reference workflows (tool/file/payment/db/message).
- `docs/` — threat model, verification method, limits.
- `sdk-typescript/` — TS SDK parity.
- `bench/` — reproducible measurements with environment disclosure.

## PR checklist

- [ ] `pytest` green + `prof demo` PASS
- [ ] New deny-path has a test (tamper/replay/expiry/scope)
- [ ] Ledger entry covered for allow + deny
- [ ] Docs updated if behavior changed
