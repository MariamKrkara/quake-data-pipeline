# Quake Data Pipeline

An incremental data pipeline that pulls earthquake data from the **USGS REST API** (GeoJSON), cleans and validates it, and loads it into **PostgreSQL**. It runs with **Docker Compose**, as a **Kubernetes CronJob**, and on an **AWS EC2** server provisioned with **Terraform**, with **GitHub Actions** CI.

I built it to practise the core of data and infrastructure engineering end to end: getting semi-structured data from an API into a reliable, queryable model, and running it in containers on cloud infrastructure defined as code.

```mermaid
flowchart LR
    API["USGS Earthquake API<br/>(REST, GeoJSON)"] -->|extract<br/>paginated, retries| T["Transform<br/>flatten + type"]
    T --> Q{"Data-quality<br/>checks"}
    Q -->|valid| D["Deduplicate<br/>(latest version)"]
    Q -->|invalid| REJ[("core.rejected_events")]
    D -->|COPY + upsert| CORE[("core.earthquakes")]
    API -.->|as received| RAW[("raw.usgs_events<br/>JSONB")]
    CORE --> V["Reporting views"]
    RUNS[("etl.pipeline_runs<br/>watermark + run log")] -.->|updatedafter| API
```

## What it does

| Stage | How |
|---|---|
| **Extract** | Calls the USGS FDSN event API with offset pagination, timeouts and exponential-backoff retries on 429/5xx errors. |
| **Incremental loading** | The first run backfills 30 days. Later runs only request events *updated after* the last successful run's watermark (minus a 10-minute overlap, so nothing is missed). |
| **Raw layer** | Every record is stored exactly as received in `raw.usgs_events` (JSONB), one row per event version, for audit and reprocessing. |
| **Transform** | Flattens nested GeoJSON into typed columns (epoch ms → `timestamptz`, coordinates → lat/lon/depth, derived `region`). |
| **Data quality** | Required fields, coordinate/depth/magnitude ranges, no future timestamps. Failing records go to `core.rejected_events` with the reasons; nothing is silently dropped. |
| **Deduplication** | If an event appears more than once, only the most recently updated version is kept. |
| **Load** | Bulk `COPY` into a temporary staging table, then one set-based `INSERT … ON CONFLICT DO UPDATE`. A row is only overwritten by a **newer** version, so replays are idempotent. |
| **Atomicity** | All data writes for a run happen in one transaction. A failed run rolls back completely and is recorded as `failed` with the error. |
| **Observability** | `etl.pipeline_runs` logs every run (fetched / inserted / updated / unchanged / rejected); `etl.v_run_health` summarises them. |

## Data model

| Schema | Table / view | Purpose |
|---|---|---|
| `raw` | `usgs_events` | Source payloads as JSONB, unique per `(event_id, source_updated_at)` |
| `core` | `earthquakes` | Clean, typed, one row per earthquake (latest revision) |
| `core` | `rejected_events` | Records that failed quality checks, with reasons |
| `core` | `v_daily_summary`, `v_region_summary` | Reporting views |
| `etl` | `pipeline_runs`, `v_run_health` | Run log and watermark |
| `etl` | `schema_migrations` | Applied SQL migrations |

Schema changes live in `sql/NNN_*.sql` and are applied automatically, once each, in order.

## Tech stack

Python 3.12 (requests, psycopg 3) · PostgreSQL 16 · Docker / Docker Compose · Kubernetes · Terraform · AWS EC2 · GitHub Actions · pytest

## Run it locally (Docker Compose)

Requires Docker Desktop (or Docker Engine with the Compose plugin).

```bash
cp .env.example .env              # then set POSTGRES_PASSWORD (letters and digits)
docker compose up -d --build      # starts PostgreSQL + the pipeline (runs every 15 min)
docker compose logs -f pipeline   # watch the first run
```

Check the results:

```bash
docker compose run --rm pipeline status

docker compose exec db psql -U quake -d quake -c "
  SELECT region, events, max_magnitude, avg_depth_km
  FROM core.v_region_summary ORDER BY events DESC LIMIT 10;"
```

Load the bundled sample file instead of calling the API (useful offline):

```bash
docker compose run --rm -v "$PWD/tests/fixtures:/data" pipeline run --source-file /data/usgs_batch_1.geojson
```

Stop everything with `docker compose down` (add `-v` to delete the data volume too).

## Run it on Kubernetes (kind)

Requires [kind](https://kind.sigs.k8s.io/) and `kubectl`. PostgreSQL runs as a StatefulSet with a persistent volume; the pipeline runs as a CronJob every 15 minutes, one short-lived pod per run.

```bash
kind create cluster --name quake
docker build -t quake-pipeline:latest .
kind load docker-image quake-pipeline:latest --name quake

kubectl apply -f k8s/00-namespace.yaml
PW=$(openssl rand -hex 24)
kubectl -n quake create secret generic quake-db \
  --from-literal=POSTGRES_USER=quake \
  --from-literal=POSTGRES_PASSWORD="$PW" \
  --from-literal=POSTGRES_DB=quake \
  --from-literal=DATABASE_URL="postgresql://quake:$PW@postgres:5432/quake"
kubectl apply -f k8s/

# trigger a run now instead of waiting for the schedule
kubectl -n quake create job first-run --from=cronjob/quake-pipeline
kubectl -n quake logs -f job/first-run
```

Clean up with `kind delete cluster --name quake`.

## Deploy to AWS (Terraform)

Terraform creates an Ubuntu 24.04 EC2 instance in the default VPC with an encrypted disk, IMDSv2 enforced, and a security group that only allows SSH from your IP. The database is never exposed to the internet. On first boot the instance installs Docker, clones this repository, generates a random database password **on the server** (so it never appears in Terraform state), and starts the stack.

Prerequisites: an AWS account, the AWS CLI configured (`aws configure`), Terraform ≥ 1.5, an SSH key (`ssh-keygen -t ed25519`), and this repository pushed to a **public** GitHub repo.

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # set allowed_ssh_cidr to <your IP>/32 and repo_url
terraform init
terraform plan
terraform apply

# after ~3–5 minutes
ssh ubuntu@$(terraform output -raw public_ip)
cd /opt/quake-data-pipeline && docker compose ps && docker compose run --rm pipeline status
```

> **Cost:** `t3.micro` is free-tier eligible in most regions, but eligibility depends on your account. Set a billing alert, and run `terraform destroy` when you are finished.

## Tests and CI

```bash
pip install -r requirements-dev.txt
pytest                                    # unit tests (no database needed)

# integration tests against a throwaway PostgreSQL database
TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/quake_test pytest -v
```

The integration tests cover the initial load, incremental updates and inserts, idempotent replays, watermark advancement, rollback of failed runs, and the reporting views. The files in `tests/fixtures/` are **synthetic** samples in the USGS format, including deliberately bad records.

GitHub Actions (`.github/workflows/ci.yml`) runs on every push: the full test suite against a PostgreSQL 16 service container, a Docker image build, and `terraform fmt` + `terraform validate`.

## Project structure

```
pipeline/            extract, transform, quality, load, runner, CLI
sql/                 ordered schema migrations and reporting views
tests/               unit + integration tests, sample GeoJSON fixtures
k8s/                 namespace, PostgreSQL StatefulSet, pipeline CronJob
infra/terraform/     AWS EC2 deployment
.github/workflows/   CI pipeline
Dockerfile, docker-compose.yml
```

## Configuration

All settings are environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | — | PostgreSQL connection string (required) |
| `MIN_MAGNITUDE` | `2.5` | Smallest magnitude to fetch |
| `BACKFILL_DAYS` | `30` | History loaded on the first run |
| `LOOKBACK_DAYS` | `30` | Event-time window for incremental runs |
| `OVERLAP_MINUTES` | `10` | Re-read margin before the watermark |
| `PAGE_SIZE` | `5000` | Records per API request |
| `INTERVAL_MINUTES` | `15` | Run frequency for `run --loop` |

## Design decisions

- **Updated-after watermark instead of event time.** USGS revises magnitudes and locations after an event, so filtering on *update* time catches revisions as well as new events. It works like change data capture against a source you don't control.
- **Raw + core layers.** Keeping untouched payloads means the curated table can be rebuilt if the transform logic changes, and every value can be traced back to the source record.
- **Newer-wins upsert.** Overlapping windows, retries and replays can never overwrite fresh data with stale data.
- **Quarantine, don't drop.** Rejected records stay visible with their reasons, so data-quality problems can be measured.

## Possible next steps

- Move the database to a managed service (Amazon RDS) and store the password in AWS Secrets Manager
- Push the image to a container registry (ECR / GHCR) from CI and deploy automatically
- Add a dashboard (Power BI or Grafana) on top of the reporting views
- Alert on failed runs or rising rejection rates
