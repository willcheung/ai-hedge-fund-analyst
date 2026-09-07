# Trading execution — disabled staging component

This checkout preserves deterministic trade-intent validation, risk checks, IBKR execution code and audit/monitoring code. It is **not an operational deployment**. Follow [the release boundaries](../docs/RELEASE.md): staging must not start services, connect to a broker or route orders; production remains unchanged.

## Safety boundary

**The code can place live bracket orders when explicitly configured to do so.** Disabled defaults are safeguards, not removal of execution capability or an OS sandbox. Do not describe this package as preview-only or as having live order placement removed.

The packaged staging configuration defaults to:

- `kill_switch: true`;
- trading/placement enable flags set to `false`;
- broker `readonly: true`;
- no account configured.

`TRADING_EXECUTION_CONFIG` selects an explicit configuration override. Such an override can change the safety posture; never point staging at an operational config. `TRADING_EXECUTION_STATE_DIR` overrides the runtime-state directory; otherwise home-safe defaults are used rather than legacy production paths. Use a disposable staging HOME and state directory, and keep credentials, account data, journals and runtime state out of Git.

## Isolated installation

In a fresh virtual environment, from this `trading-execution/` directory:

```sh
pip install --require-hashes -r requirements-test.txt
pip install --no-deps --no-build-isolation .
```

Use Python 3.12 for this lock; package metadata permits Python >=3.11 but the locked verification target is 3.12. The lock supplies setuptools, wheel and pytest as well as runtime dependencies. Use the shared isolation wrapper described in [RELEASE.md](../docs/RELEASE.md) for all package installation and tests. Application tests must use synthetic fixtures, no network, no production HOME and no broker processes. Do not run application imports, CLI commands (including `--help`), broker health checks, monitors or execution scripts as a deployment smoke test.

## Explicit exclusions

- Optional legacy scripts requiring explicit ANALYST_* inputs remain excluded from the staging execution/installation path. They are retained source for **syntax-only** checking, not approved runnable entrypoints or proof of portability.
- The privately provisioned signal evaluator is an external, excluded evaluator. It was not inspected for this documentation work; its existence does not establish clean-checkout test coverage.
- Broker gateways, credentials, account provisioning, external profile dependencies, live inputs and operational scheduling are not provisioned here. No claim of complete production operation is made.

## Deployment status

No service/timer is installed or enabled, and no inert placeholder is presented as a working deployment. Broker/evaluator service provisioning is explicitly deferred until a separately approved operational deployment. The staging surface is the package with disabled defaults. Test results must come from a successful isolated run of the current source.

Future deployment requires separate explicit approval, reviewed entrypoints and configuration, dependency/credential provisioning, broker and account safeguards, and a tested rollback procedure. This checkout does not replace or migrate existing legacy operational entrypoints.
