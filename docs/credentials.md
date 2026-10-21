# GENESIS credentials

The Destatis connector talks to two GENESIS installations. Each needs its own free registration; a token from one is not valid on the other.

| Host | `host` name | Base URL | Env vars | Register |
|------|-------------|----------|----------|----------|
| GENESIS-Online (Statistisches Bundesamt) | `genesis` (default) | `https://genesis.destatis.de/genesisWS/rest/2020/` | `GENESIS_TOKEN`, or `GENESIS_USER` and `GENESIS_PASSWORD` | https://genesis.destatis.de/datenbank/online/ |
| Regionalstatistik (Regionaldatenbank Deutschland, IT.NRW) | `regionalstatistik` | `https://www.regionalstatistik.de/genesisws/rest/2020/` | `REGIONALSTATISTIK_TOKEN`, or `REGIONALSTATISTIK_USER` and `REGIONALSTATISTIK_PASSWORD` | https://www.regionalstatistik.de/datenbank/online/ |

Registration is self-service (same-day in our own experience). The token is shown in the web UI under "Webservice-Schnittstelle (API)"; generating a new one invalidates the old one immediately (Anwenderdokumentation Webservice/API v5.1, section 2.1.3).

## Two paths

- **Token** (default): the token travels in the `username` HTTP header with an empty `password`. Enough for table downloads.
- **User plus password**: needed for `job=true` (batch jobs for tables too large to download directly) and `profile/*` calls. Both values travel as HTTP headers.

Credentials never go into the URL or the form body: the server ignores body credentials and silently runs the call as guest (`Username: GAST`), which the client treats as an authentication failure. Redirects are not followed with credentials attached.

## Resolution order

1. Explicit: `DestatisCredentials(host="genesis", token=...)` (or `user=..., password=...`) passed to `GenesisClient`, or in mloda `Options(context={"genesis_credentials": DestatisCredentials(...)})`. Only the instance is accepted (its repr is redacted; a plain dict would print its values with the options), and only in `context`: the key is refused in `group`, which is hashed and printed with the feature.
2. Env vars of the host, chosen by the host prefix. Whitespace is stripped. A half-set pair (`GENESIS_USER` without `GENESIS_PASSWORD`, or the reverse) is an error, never a fallback to the token or to the other host.
3. Otherwise `MissingCredentialsError` names the env vars and the registration page for that host. Nothing is sent.

Credentials scoped to one host are refused on the other (`WrongHostCredentialsError`), and env resolution never falls back across hosts.

Credentials are needed on a cache miss only: a selection already in the parameter cache is served without them, so an offline rerun (and `peek` on a cached table) works with no env vars set.

```python
from mloda_plugin_govdata.feature_groups.destatis import GenesisClient

with GenesisClient("genesis") as client:  # credentials from GENESIS_TOKEN
    client.logincheck()  # raises GenesisAuthError if rejected or run as guest
```

## Result too large

A table over the host's download limit raises `GenesisResultTooLarge` (GENESIS status code 98, or the "too large" status text). Ways out:

- Shrink the selection: fewer `regionalkey` entries, classifying keys, or years.
- Split it into several selections, one feature per selection; each is cached under its own parameters.
- Fetch the table by hand through the host's web portal (the registration page above).

`job=true` (the host prepares the table for a later download) needs the user-plus-password path, but this connector does not submit or fetch jobs (deferred, see [destatis-options.md](destatis-options.md#deferred)); a host that queues a job on its own raises `GenesisJobAccepted`.

## Redaction

`repr` and `str` of `DestatisCredentials` and of the `logincheck` reply are redacted, and every `GenesisError` raised by `GenesisClient.call` (and the methods built on it) has the known secrets scrubbed from its text. The `Parameter` block that GENESIS echoes in each JSON reply loses `username` and `password` at parse time. Errors raised below that layer (transport errors, a `ValueError` from your own code) are not scrubbed. The fixture capture script (`scripts/capture_genesis_fixtures.py`) redacts secret values in any case or URL-encoding before writing and refuses to keep a file in which a secret survived.

## Live tests

Tests marked `genesis_live` are deselected by default and skip with a visible reason when no credentials are set. Run them per host with the env vars above:

```bash
GENESIS_TOKEN=... pytest -m "live and genesis_live"
```

## Notebooks

The demo notebook's Destatis chapters and the Destatis tutorial resolve credentials the same way and skip themselves, naming the reason, when none are set.
