# Integration Adapter Framework

Every enterprise customer has a different system of record: a CRM with an API, an ERP that drops CSVs on SFTP every night, a homegrown database. This framework makes each new one an adapter of about a hundred lines. Auth, pagination, retries, rate limits, incremental sync and checkpointing are written once in the base class.

```
config/acme.yaml ──► registry ──► Adapter (auth + fetch pages) ──► Record (normalised) ──► sink
                                       ▲                                   │
                                  checkpoint store ◄── cursor saved after each page ┘
```

## Writing an adapter

```python
@register("rest_crm")
class RestCRM(HttpAdapter):
    def pages(self, since):                         # yield lists of raw items
        yield from self.paginate_cursor("/v2/accounts", params={"updated_after": since})

    def to_record(self, item) -> Record:            # raw item → our shape
        return Record(source=self.name, kind="account", external_id=item["id"],
                      updated_at=item["updated_at"], data={"name": item["name"], "tier": item.get("tier")})
```

The base class gives you `get()` with retry (429/5xx, exponential backoff with jitter, honours `Retry-After`), a client-side rate limiter, three pagination styles (cursor, page number, `Link` header) and OAuth2 client-credentials or API-key auth from config.

## Running a sync

```bash
pip install -e ".[dev]"
python -m adapters.run config/acme.yaml              # incremental: resumes from the last checkpoint
python -m adapters.run config/acme.yaml --full       # ignore checkpoint, re-pull everything
```

## Guarantees

- **Resumable.** The checkpoint (max `updated_at` seen) is saved after every page, so a sync that dies at page 400 restarts at page 400, not page 1.
- **At-least-once, idempotent downstream.** Records carry `(source, external_id, updated_at)`. The sink upserts on that key, so a replayed page changes nothing.
- **Secrets from the environment.** Config files name environment variables (`client_secret_env: ACME_CRM_SECRET`), never values.

## Layout

```
adapters/base.py               Adapter, HttpAdapter (auth, retry, rate limit, pagination), Record
adapters/registry.py           @register and lookup by type name
adapters/checkpoint.py         JSON-file checkpoint store (swap for a DB table in production)
adapters/run.py                load config → build adapter → sync with checkpoints
adapters/connectors/rest_crm.py   example: OAuth2 + cursor pagination
adapters/connectors/sftp_csv.py   example: nightly CSV drop over SFTP
config/acme.yaml               example customer config
tests/                         pagination, retry and checkpoint tests with a mock transport
```
