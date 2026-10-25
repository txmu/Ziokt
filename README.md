# Ziokt

[简体中文](README.zh-CN.md) · [Documentation](docs/README.md) · [v1.0 downloads](https://github.com/txmu/Ziokt-Releases/releases/tag/v1.0)

Ziokt is a distributed application and collaboration platform for independently operated nodes. It brings content, private communities, verifiable builds, software delivery, naming and node operations into one application system. Corium supplies native chain and governance services; Shadow6 supplies independently deployable native transports. Each project retains its own authority and can run on its own.

## What a node provides

| Area | Components | What to expect |
| --- | --- | --- |
| Applications | Community, Library, Netnews, browser reader, sites, chat | Persistent application state with explicit membership and publication policies |
| Build and delivery | OpenCI, Content Fabric, dCPM/UFS | Source commitments, isolated workers, signed receipts, verified packages and separate activation |
| Access | Gateway, node ZDNS, MCP, desktop/mobile/PWA clients | Scoped interfaces to actual configured services |
| Native foundations | Corium, Shadow6, typed companion boundaries | Native authorization and transport capabilities remain with their owning projects |
| Operations | Independent identities, recovery, node exclusions | Explicit network configuration, reviewable evidence and bounded failure handling |

A stored object, a running process, an accepted block and a completed application action are different observations. Ziokt keeps their evidence separate.

## Start with a prebuilt node

Use the [VPS guide](https://github.com/txmu/Ziokt-Releases/blob/main/VPS_BOOTSTRAP.zh-CN.md) for runtime prerequisites and network selection. After installing those prerequisites:

```sh
curl --proto '=https' --tlsv1.2 -fsSL https://raw.githubusercontent.com/txmu/Ziokt-Releases/main/install.sh | sudo sh -s -- --root /opt/ziokt-node bootstrap --install --runtime --yes --enable-services --connectivity public --network ziokt-acceptance --service-prefix ziokt-acceptance
```

This installs checked CI products and creates a fresh acceptance network. Joining an existing network additionally requires its public genesis, seed endpoint and public certificate with independently checked hashes. Every node generates its own keys. Bootstrap keeps consensus on hold until history is verified. Management interfaces bind to loopback by default.

## Work from source

Python 3.11+ is required. Use an isolated environment and the pinned requirements:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m ziokt --help
.venv/bin/python tools/sync_providers.py --check
```

Native integration uses adjacent `../Corium` and `../Shadow6` checkouts, or the explicit root overrides documented in the [getting started guide](docs/guide/getting-started.en.md). `native-sources.lock.json` pins the runtime source revisions used by CI. Heavy compilation belongs in CI; the joint source ZIP is a UTF-8 text exchange package and contains no runnable native binaries.

## Choose a guide

- [Getting started](docs/guide/getting-started.en.md): installation, source checkout and first read-only checks.
- [Architecture](docs/guide/architecture.en.md): application ownership and cross-component data flow.
- [Operations](docs/guide/operations.en.md): configuration, peers, exclusions and recovery.
- [Security and privacy](docs/guide/security.en.md): trust boundaries, anonymous routing and publication.
- [Verification and release](docs/guide/verification.en.md): Lean correspondence, CI evidence and known limits.
- [Complete document catalog](docs/REFERENCE.en.md): every maintained component guide and historical report.

## Assurance

The ecosystem release remains **v1.0**; Ziokt application projects use `1.0.0`. Lean models and generated production predicates supplement existing Ada/SPARK and Idris contracts. They do not prove every implementation, dependency, FFI or operating-system behavior. Read the exact revision and acceptance scope in the release evidence. Multi-process CI does not replace independent physical VPS acceptance.

[Corium](https://github.com/txmu/Corium) · [Shadow6](https://github.com/txmu/Shadow6) · [Release and deployment tools](https://github.com/txmu/Ziokt-Releases)
