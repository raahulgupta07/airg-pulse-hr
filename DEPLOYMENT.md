# PULSE — Deployment & Operations

## Data Persistence

PULSE stores two categories of state on disk: the PostgreSQL database
(`pgdata`) and CV / artifact files (`hire-data`). Both are declared as
**named Docker volumes** in `compose.yaml`. Named volumes survive the normal
`docker compose down` lifecycle and are only destroyed by an explicit
`docker compose down -v` or `docker volume rm`.

### Volume map

| Volume      | Stores                                            | Survives `down`? | Survives `down -v`? | Prod recommendation                              |
|-------------|---------------------------------------------------|------------------|---------------------|--------------------------------------------------|
| `pgdata`    | PostgreSQL 18 + pgvector data dir (`/var/lib/postgresql`) | Yes              | **No** (destroyed)  | Keep as named volume; back up via `backup` sidecar + `pre_upgrade.sh` |
| `hire-data` | Uploaded CVs, parsed artifacts, screenshots (`/data` in `pulse-api`) | Yes              | **No** (destroyed)  | **Convert to bind mount** so files live on host disk, are visible to ops, and are trivially backed up by host snapshots |

Both volumes are NAMED (the `volumes:` block at the bottom of
`compose.yaml` lists `pgdata:` and `hire-data:` with no `driver_opts`),
**not anonymous**. Verified by inspecting the compose file — there are no
unnamed `- /some/path` mount entries.

### Bind-mount conversion snippet (production)

For prod, replace the named `hire-data` mount on the `api` service so CVs
land on the host filesystem:

```yaml
# compose.yaml — api service
    volumes:
      # DEV (default): named volume, opaque to host
      # - hire-data:/data
      # PROD: bind mount, visible to host ops + host backup tools
      - ./data/cvs:/data
```

Then `mkdir -p ./data/cvs && chown -R 1000:1000 ./data/cvs` (or whichever
UID the container runs as). Remove `hire-data:` from the bottom-of-file
`volumes:` block once nothing references it.

### `docker volume inspect pgdata` — sample output

```json
[
    {
        "CreatedAt": "2026-04-12T10:14:22Z",
        "Driver": "local",
        "Labels": {
            "com.docker.compose.project": "hub-hr-agent",
            "com.docker.compose.volume": "pgdata"
        },
        "Mountpoint": "/var/lib/docker/volumes/hub-hr-agent_pgdata/_data",
        "Name": "hub-hr-agent_pgdata",
        "Options": null,
        "Scope": "local"
    }
]
```

The `Mountpoint` is where Docker stores the bytes on the host. On macOS /
Windows this lives inside the Docker Desktop VM, **not** on the user's
filesystem — which is exactly why prod should bind-mount `/data`.

### Backup strategy (defense in depth)

1. **Continuous (sidecar)** — `backup` service in `compose.yaml` runs
   `pg_dump -F c | gzip` every 24h into `./data/backups/`, keeps 14 days,
   maintains a `latest.dump.gz` symlink.
2. **Pre-upgrade snapshot** — `bash scripts/pre_upgrade.sh` captures DB
   dump + tarball of `hire-data` + manifest JSON (image SHA, git commit,
   db size). Run this immediately before every `docker compose up -d --build`.
3. **Off-host** — sync `./data/backups/` to S3 / B2 / rsync target on a
   cron (out of scope for compose).

### Disaster recovery flow

| Scenario | Recovery |
|---|---|
| Bad deploy, app crashes | `git revert` → `docker compose up -d --build`. No data lost (volumes intact). |
| `docker compose down -v` ran by mistake | Volumes gone. `bash scripts/restore.sh data/backups/latest.dump.gz --confirm` rebuilds DB. CVs restored from `cvs_<ts>.tar.gz`: `docker run --rm --volumes-from pulse-api -v $PWD/data/backups:/in alpine sh -c "cd /data && tar xzf /in/cvs_<ts>.tar.gz"`. |
| Host disk failure | Restore `./data/backups/` from off-host backup, then run the same restore commands. |
| Schema corruption | Pick a known-good `pre_upgrade_*.dump.gz`, run `restore.sh <file> --confirm`. |
| Need point-in-time older than 14d | Pull from off-host archive; sidecar only keeps 14d locally. |

After any restore, `scripts/restore.sh` automatically curls
`http://localhost:${PORT:-8090}/api/health` and reports the result.

### Operational runbook

```bash
# Pre-deploy snapshot (every release)
bash scripts/pre_upgrade.sh
docker compose up -d --build

# List backups
ls -lh data/backups/

# Restore latest (DESTRUCTIVE)
bash scripts/restore.sh data/backups/latest.dump.gz --confirm

# Inspect sidecar
docker compose logs -f backup

# Confirm volumes are NAMED
docker volume ls | grep -E 'pgdata|hire-data'
```

### Environment variables

Full env reference lives in `README.md`. Operationally relevant additions:

```bash
# AI matching behavior
MATCH_ON_CV_UPLOAD=false   # if true, every new CV scans all open positions (slow + costly).
                           # default false: matching only runs on position create / JD update / manual rescan.
```

