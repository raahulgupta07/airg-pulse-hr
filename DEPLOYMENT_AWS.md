# DEPLOYMENT_AWS.md — HUB-HR-Agent (pulse) on AWS

Operator guide for deploying and running the HUB-HR-Agent ("pulse") application
on AWS. Target stack: ECS Fargate + Aurora Postgres Serverless v2 + EFS +
Secrets Manager + ALB, fronted by Route53 and ACM, deployed by GitHub Actions
via OIDC.

> Region: `us-east-1` (override with `AWS_REGION`).
> Environment naming: `prod`, `staging` — used as the `env_name` Terraform var
> and as the suffix on most AWS resources (`pulse-prod`, `pulse-staging`).

---

## 1. Architecture

```
                                  Internet
                                     │
                              ┌──────▼──────┐
                              │   Route53   │  pulse.example.com  (A-ALIAS)
                              └──────┬──────┘
                                     │
                              ┌──────▼──────┐
                              │     ACM     │  TLS cert (us-east-1)
                              └──────┬──────┘
                                     │ :443
                       ┌─────────────▼─────────────┐
                       │   Application Load        │   public subnets
                       │   Balancer (pulse-<env>)  │   + WAFv2 (optional)
                       └──────┬─────────────┬──────┘
                              │             │
                          target group  health checks /api/health
                              │
        ┌─────────────────────▼──────────────────────┐
        │      ECS Cluster: pulse-<env>              │
        │  ┌──────────────────────────────────────┐  │
        │  │ Service: pulse-api  (Fargate)        │  │   private subnets
        │  │  task: pulse-api   (0.5 vCPU / 1 GB) │  │
        │  │  container: pulse-api  (image=ECR)   │  │
        │  │   ├── EFS mount  /data  (uploads)    │  │
        │  │   ├── env from   SSM Parameter Store │  │
        │  │   ├── secrets from Secrets Manager   │  │
        │  │   └── logs → CloudWatch /ecs/pulse-* │  │
        │  └──────────────────────────────────────┘  │
        └────┬─────────────┬──────────────┬──────────┘
             │             │              │
       ┌─────▼─────┐ ┌─────▼─────┐  ┌─────▼──────┐
       │ Aurora PG │ │   EFS     │  │  Secrets   │
       │ Serverlessv2│ pulse-<env>│  │  Manager   │
       │ pulse-<env>│ │ /data     │  │ pulse/<env>│
       └───────────┘ └───────────┘  └────────────┘
                              │
                       ┌──────▼──────┐
                       │ NAT Gateway │ → outbound for ECR pulls / API calls
                       └─────────────┘

       CloudTrail + VPC flow logs + GuardDuty cover the whole VPC.
       ECR (pulse-api) holds versioned multi-arch images (amd64 + arm64).
```

---

## 2. Prerequisites

| Item                     | Notes |
| ------------------------ | ----- |
| AWS account              | with admin or a sufficiently scoped IAM user |
| A registered domain      | e.g. `pulse.example.com`. Route53 hosted zone preferred but any DNS works (CNAME) |
| ACM certificate          | issued in **the same region as the ALB** (`us-east-1`), DNS-validated |
| Terraform                | **>= 1.6** |
| AWS CLI                  | **v2** |
| Docker                   | with `buildx` (multi-arch). Docker Desktop ships it. |
| GitHub repo              | OIDC trust to an AWS IAM role (see §3.2) |
| `gh` CLI                 | optional, used for `gh workflow run` |
| SSM Session Manager plugin | needed for `exec-shell.sh` |

> **If you see `unsupported Terraform version`** — upgrade to >= 1.6.
> **If `docker buildx` is missing** — install Docker Desktop or `docker buildx install`.

---

## 3. One-time bootstrap

### 3.1 Terraform remote state

Create the state bucket and lock table once per account:

```bash
AWS_REGION=us-east-1
ACCT=$(aws sts get-caller-identity --query Account --output text)
BUCKET="pulse-tfstate-${ACCT}"

aws s3api create-bucket \
  --bucket "$BUCKET" \
  --region "$AWS_REGION"

aws s3api put-bucket-versioning \
  --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
  --bucket "$BUCKET" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

aws s3api put-public-access-block \
  --bucket "$BUCKET" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

aws dynamodb create-table \
  --region "$AWS_REGION" \
  --table-name pulse-tfstate-lock \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema           AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST
```

> **`BucketAlreadyOwnedByYou`** — bucket already exists in your account; safe.
> **`BucketAlreadyExists`** — global namespace clash, change `BUCKET` name.

### 3.2 GitHub Actions OIDC role

Create the role GitHub Actions assumes. Replace `OWNER/REPO` and `ACCT`.

`trust-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Federated": "arn:aws:iam::ACCT:oidc-provider/token.actions.githubusercontent.com" },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
      },
      "StringLike": {
        "token.actions.githubusercontent.com:sub": "repo:OWNER/REPO:*"
      }
    }
  }]
}
```

`permissions.json` (minimum for the deploy workflow):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:CompleteLayerUpload",
        "ecr:InitiateLayerUpload",
        "ecr:PutImage",
        "ecr:UploadLayerPart",
        "ecr:DescribeRepositories",
        "ecr:BatchGetImage"
      ], "Resource": "*" },
    { "Effect": "Allow", "Action": [
        "ecs:DescribeServices",
        "ecs:UpdateService",
        "ecs:RegisterTaskDefinition",
        "ecs:DescribeTaskDefinition",
        "ecs:ListTasks",
        "ecs:DescribeTasks"
      ], "Resource": "*" },
    { "Effect": "Allow", "Action": [
        "rds:CreateDBClusterSnapshot",
        "rds:DescribeDBClusterSnapshots"
      ], "Resource": "*" },
    { "Effect": "Allow", "Action": [
        "iam:PassRole"
      ], "Resource": "arn:aws:iam::ACCT:role/pulse-*" }
  ]
}
```

Create the OIDC provider (once per account) and the role:

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1

aws iam create-role \
  --role-name pulse-gha-deploy \
  --assume-role-policy-document file://trust-policy.json

aws iam put-role-policy \
  --role-name pulse-gha-deploy \
  --policy-name pulse-gha-deploy-inline \
  --policy-document file://permissions.json
```

Then in GitHub → **Settings → Environments** create `staging` and `prod`, and
under each set the following **Variables** (not secrets — they are not
sensitive):

| Variable               | Example value |
| ---------------------- | ------------- |
| `AWS_DEPLOY_ROLE_ARN`  | `arn:aws:iam::ACCT:role/pulse-gha-deploy` |
| `AWS_REGION`           | `us-east-1` |
| `ECR_REPO`             | `ACCT.dkr.ecr.us-east-1.amazonaws.com/pulse-api` |
| `ECS_CLUSTER`          | `pulse-prod` (or `pulse-staging`) |
| `ECS_SERVICE`          | `pulse-api` |
| `ALB_DNS`              | `pulse.example.com` |
| `RDS_CLUSTER_ID`       | `pulse-prod` |

> **`Not authorized to perform: sts:AssumeRoleWithWebIdentity`** — the `sub`
> claim in the trust policy doesn't match. Print the failing run's claims with
> `actions/github-script` and tighten the `StringLike` glob.

### 3.3 ACM certificate

```bash
aws acm request-certificate \
  --region us-east-1 \
  --domain-name "pulse.example.com" \
  --validation-method DNS
```

Copy the CNAME validation record into your DNS provider; the cert moves to
`ISSUED` within minutes. Capture its ARN — you will pass it to Terraform.

### 3.4 Terraform apply

```bash
cd deploy/aws/terraform
terraform init \
  -backend-config="bucket=pulse-tfstate-${ACCT}" \
  -backend-config="key=pulse/prod.tfstate" \
  -backend-config="region=us-east-1" \
  -backend-config="dynamodb_table=pulse-tfstate-lock"

terraform plan  -var "env_name=prod" -var "aws_region=us-east-1" \
                -var "acm_cert_arn=arn:aws:acm:us-east-1:ACCT:certificate/..."
terraform apply -var "env_name=prod" -var "aws_region=us-east-1" \
                -var "acm_cert_arn=arn:aws:acm:us-east-1:ACCT:certificate/..."
```

> **`Error acquiring the state lock`** — a previous apply was killed.
> `terraform force-unlock <ID>` after confirming nobody else is applying.
> **`InvalidParameterValue: db.serverless ...`** — Aurora Serverless v2 isn't
> available in your selected AZs. Pick a region/AZ combo from the
> [Aurora region list](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Concepts.AuroraFeaturesRegionsDBEngines.grids.html).

### 3.5 Seed the SUPERADMIN password

Bootstrap helper does this in one shot:

```bash
ENV_NAME=prod AWS_REGION=us-east-1 IMAGE=pulse:latest \
  bash deploy/aws/scripts/bootstrap.sh
```

Manual equivalent:

```bash
HASH=$(docker run --rm pulse:latest python -m backend.scripts.hash_pw 'YourStrongPass')
aws secretsmanager put-secret-value \
  --region us-east-1 \
  --secret-id pulse/prod/superadmin_pass_hash \
  --secret-string "$HASH"
```

> **`ResourceNotFoundException`** — Terraform hasn't created the secret yet,
> re-run `terraform apply`. Use `create-secret` instead of `put-secret-value`
> only on a fresh secret.

### 3.6 DNS

If using Route53 — Terraform creates the A-ALIAS record automatically.
Otherwise create a CNAME at your DNS provider:

```
pulse.example.com.  CNAME  pulse-prod-1234567890.us-east-1.elb.amazonaws.com.
```

The ALB DNS is in the Terraform output `alb_dns_name`.

### 3.7 First deploy

```bash
gh workflow run deploy-aws.yml -f env=prod
gh run watch
```

Or push to `main` (auto-deploys to **staging** only).

---

## 4. Day-2 operations

### 4.1 Logs

```bash
ENV_NAME=prod bash deploy/aws/scripts/tail-logs.sh
ENV_NAME=prod FILTER='ERROR' bash deploy/aws/scripts/tail-logs.sh
ENV_NAME=prod SINCE=1h bash deploy/aws/scripts/tail-logs.sh
```

> **`ResourceNotFoundException` on the log group** — first deploy hasn't run yet,
> or the env name is wrong (`/ecs/pulse-api-<env>`).

### 4.2 Shell into a task

```bash
ENV_NAME=prod bash deploy/aws/scripts/exec-shell.sh
```

> **`The execute command failed because execute command was not enabled`** —
> ECS Exec isn't on for the service. Re-apply Terraform (Enable‑ECS‑Exec is
> a service flag) and force a new deployment. Existing tasks must be
> recycled before exec works.
> **`SessionManagerPlugin is not found`** — install the plugin (see §2).

### 4.3 Connect to the database

Two paths, depending on how locked-down the cluster is.

**A. RDS Data API** (no networking required, good for ad-hoc queries):

```bash
aws rds-data execute-statement \
  --resource-arn "arn:aws:rds:us-east-1:ACCT:cluster:pulse-prod" \
  --secret-arn   "arn:aws:secretsmanager:us-east-1:ACCT:secret:pulse/prod/db-XXXX" \
  --database     "pulse" \
  --sql          "select count(*) from users;"
```

> Requires `enable_http_endpoint = true` on the cluster (Terraform sets this).

**B. psql via a bastion** (full session, transactions, `\dt`, etc.):

```bash
# 1. Launch a t4g.nano bastion in a public subnet of the same VPC
#    (Terraform module `bastion` is opt-in: -var "enable_bastion=true").
# 2. Open SSM Session Manager — no SSH key needed.
aws ssm start-session --target i-0123456789abcdef0

# 3. From the bastion:
sudo dnf install -y postgresql15
DBHOST=$(aws rds describe-db-clusters \
  --db-cluster-identifier pulse-prod \
  --query 'DBClusters[0].Endpoint' --output text)
DBPASS=$(aws secretsmanager get-secret-value \
  --secret-id pulse/prod/db --query SecretString --output text \
  | python3 -c 'import json,sys;print(json.loads(sys.stdin.read())["password"])')
PGPASSWORD="$DBPASS" psql -h "$DBHOST" -U pulse -d pulse
```

> **`FATAL: no pg_hba.conf entry`** — your bastion's SG isn't in the cluster's
> ingress allowlist. Add it or set `bastion_sg_id` in Terraform.

### 4.4 Manual DB snapshot

```bash
ENV_NAME=prod bash deploy/aws/scripts/db-snapshot.sh "before-major-migration"
```

### 4.5 Restore from snapshot

Restoring creates a **new cluster** (you cannot restore in-place):

```bash
aws rds restore-db-cluster-from-snapshot \
  --db-cluster-identifier pulse-prod-restore \
  --snapshot-identifier   pulse-prod-pre-deploy-abc123 \
  --engine aurora-postgresql

aws rds create-db-instance \
  --db-instance-identifier pulse-prod-restore-1 \
  --db-cluster-identifier  pulse-prod-restore \
  --db-instance-class      db.serverless \
  --engine aurora-postgresql
```

Then either point the ECS task definition at the new cluster's endpoint
(redeploy), or rename clusters once you're happy:

```bash
aws rds modify-db-cluster --db-cluster-identifier pulse-prod         --new-db-cluster-identifier pulse-prod-old --apply-immediately
aws rds modify-db-cluster --db-cluster-identifier pulse-prod-restore --new-db-cluster-identifier pulse-prod     --apply-immediately
```

### 4.6 Scaling

```bash
# Horizontal — more tasks
aws ecs update-service \
  --cluster pulse-prod --service pulse-api --desired-count 4

# Or adjust the autoscaling target (Terraform-managed; preferred):
aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --resource-id service/pulse-prod/pulse-api \
  --scalable-dimension ecs:service:DesiredCount \
  --min-capacity 2 --max-capacity 10
```

For Aurora Serverless v2:

```bash
aws rds modify-db-cluster \
  --db-cluster-identifier pulse-prod \
  --serverless-v2-scaling-configuration MinCapacity=0.5,MaxCapacity=8 \
  --apply-immediately
```

### 4.7 Update an env var

Non-secret config lives in SSM Parameter Store:

```bash
aws ssm put-parameter \
  --name "/pulse/prod/FEATURE_FLAG_FOO" \
  --type String --value "true" --overwrite

aws ecs update-service \
  --cluster pulse-prod --service pulse-api --force-new-deployment
```

For secrets use Secrets Manager (`aws secretsmanager put-secret-value`) and
likewise force a new deployment — values are pulled at task start.

> **Changes don't show up** — you forgot `--force-new-deployment`. Tasks read
> SSM/Secrets only at boot.

**AI matching behavior**:

```bash
# AI matching behavior
MATCH_ON_CV_UPLOAD=false   # if true, every new CV scans all open positions (slow + costly).
                           # default false: matching only runs on position create / JD update / manual rescan.
```

Push as a non-secret SSM parameter (`/pulse/<env>/MATCH_ON_CV_UPLOAD`) and
force a new deployment as above.

---

## 5. Cost (us-east-1, on-demand)

Idle = realistic floor for a single-tenant prod env handling occasional
traffic. Light usage = a few thousand requests/day, a couple of users.

| Component                              | Idle    | Light usage |
| -------------------------------------- | ------- | ----------- |
| Aurora Serverless v2 (min 0.5 ACU)     | $45     | $80         |
| Fargate 1 task @ 0.5 vCPU / 1 GB       | $13     | $13         |
| ALB (1 LCU baseline)                   | $22     | $25         |
| NAT Gateway (1 AZ)                     | $32     | $35         |
| EFS (~1 GB, infrequent access)         | $0.30   | $1          |
| CloudWatch logs (~1 GB ingest)         | $0.50   | $5          |
| Secrets Manager × 5                    | $2      | $2          |
| Route53 hosted zone                    | $0.50   | $0.50       |
| ECR storage (~2 GB)                    | $0.20   | $0.20       |
| Data transfer                          | ~$0     | $5          |
| **Total**                              | **~$115/mo** | **~$200/mo** |

Levers if cost matters more than HA:
- Drop NAT Gateway and use **VPC endpoints** for ECR/S3/Secrets/SSM/CloudWatch (~$22/mo of endpoints replaces $32/mo NAT — break-even at ~7 endpoints, win on egress).
- Single AZ (no NAT redundancy, no multi-AZ Aurora replica) — cuts ~$30/mo.
- Aurora **min 0 ACU** (auto-pause, requires v2.07+ engine) — $0 idle DB compute, ~10 s cold start.

---

## 6. Local Docker vs ECS parity

| Concern        | Local (`docker compose`)             | AWS ECS                                      |
| -------------- | ------------------------------------ | -------------------------------------------- |
| App image      | built locally from `Dockerfile.prod` | ECR `pulse-api:<sha>` (multi-arch)           |
| Database       | local `postgres:16` container        | Aurora Postgres Serverless v2                |
| File storage   | bind-mounted `./data`                | EFS mounted at `/data`                       |
| Secrets        | `.env` file                          | Secrets Manager → injected as env at boot    |
| Non-secret env | `.env`                               | SSM Parameter Store → injected as env at boot |
| Logs           | container stdout, `docker logs`      | CloudWatch Logs `/ecs/pulse-api-<env>`, JSON |
| TLS            | none (http://localhost)              | ACM cert on ALB, HTTPS only                  |
| Auth subject   | `localhost` cookies                  | `pulse.example.com`, secure cookies          |
| Reverse proxy  | none / Caddy in compose              | ALB                                          |
| Scaling        | one container                        | Fargate desired-count + autoscaling          |
| Restart policy | docker `unless-stopped`              | ECS replaces failed tasks                    |

Behavioural differences to watch for:
- Log lines on ECS are wrapped in CloudWatch JSON (`message`, `timestamp`,
  `awslogs-stream`). The app should log structured JSON to stdout so both
  environments stay greppable.
- Local `./data` survives `docker compose down`; EFS survives task replacement
  but will be **deleted** if Terraform destroys the EFS resource. Snapshot
  before destroy.

---

## 7. Disaster recovery

### 7.1 Point-in-time restore (Aurora)

PITR retention is 7 days by default (Terraform var
`backup_retention_period`).

```bash
aws rds restore-db-cluster-to-point-in-time \
  --source-db-cluster-identifier pulse-prod \
  --db-cluster-identifier        pulse-prod-pitr \
  --restore-to-time              2026-05-04T12:34:00Z

aws rds create-db-instance \
  --db-instance-identifier pulse-prod-pitr-1 \
  --db-cluster-identifier  pulse-prod-pitr \
  --db-instance-class db.serverless --engine aurora-postgresql
```

Cut over by editing the ECS task def's `DB_HOST` (SSM) and forcing a redeploy,
or by renaming clusters as in §4.5.

### 7.2 Total cluster loss / region rebuild

1. From a fresh laptop: `git clone`, `cd deploy/aws/terraform`.
2. State is in S3 (versioned). If the **state itself** is intact:
   ```bash
   terraform init -backend-config=...
   terraform apply -var "env_name=prod" ...
   ```
   AWS will recreate everything. EFS and RDS data are gone unless restored
   from snapshot.
3. If state is lost too: import the surviving snapshot, then
   `terraform import` the new resources OR start with a clean state and let
   Terraform create new resources, restoring data via §7.1/§4.5.
4. Re-seed secrets (§3.5).
5. Re-point DNS (Route53 alias is recreated automatically; external DNS needs
   a CNAME update).

> Keep a **monthly export of the Terraform state** to a separate account/region.
> S3 versioning protects against accidental edits but not account compromise.

### 7.3 Bad deploy

The deploy job already does a snapshot + `update-service` + smoke test +
auto-rollback to the previous task definition on failure. Manual rollback:

```bash
aws ecs update-service \
  --cluster pulse-prod --service pulse-api \
  --task-definition pulse-api:42 \
  --force-new-deployment
```

---

## 8. Security hardening checklist

- [ ] **ECS Exec** enabled on the service (audit logs to CloudWatch).
- [ ] **ECR scan-on-push** enabled (`scan_on_push = true` in Terraform).
- [ ] **KMS-CMK encryption** on:
      EFS (`encrypted = true` + KMS key),
      Secrets Manager (per-env key),
      RDS (`storage_encrypted = true` + KMS key),
      CloudWatch log groups.
- [ ] **CloudTrail** organisation trail to S3 (separate account ideally).
- [ ] **VPC Flow Logs** to CloudWatch, 30-day retention.
- [ ] **GuardDuty** enabled in the region.
- [ ] **WAFv2** web ACL on the ALB: AWS managed `CommonRuleSet`,
      `KnownBadInputs`, plus a rate-based rule (e.g. 2000 req / 5 min / IP).
- [ ] **Security groups**: ALB SG → ECS SG (only); ECS SG → RDS SG (5432) and
      EFS SG (2049). No 0.0.0.0/0 ingress except ALB :443.
- [ ] **No public IPs on Fargate tasks** (`assign_public_ip = false`).
- [ ] **IAM**: per-env task role, least-privilege Secrets/SSM read; no `*`.
- [ ] **GitHub OIDC** trust policy scoped to specific `ref:refs/heads/main` /
      `environment:prod` for prod role; broader for staging.
- [ ] **Container** runs as non-root user, read-only root FS where possible
      (writable only `/data` EFS mount and `/tmp`).
- [ ] **SUPERADMIN password** rotated on first login; bcrypt cost ≥ 12.
- [ ] **Dependabot** + GHA `permissions: read-all` default.

---

## 9. Adding more services later (Scout, future agents)

The VPC, ALB, ECR registry, NAT, secrets KMS key, and CloudWatch are
**shared infra**. Each new app gets its own ECS service + task def + DB
schema (or its own cluster, depending on isolation requirements).

Recommended layout:

```
deploy/aws/terraform/
├── modules/
│   ├── vpc/           # one per account
│   ├── alb/           # one per account (multi-host)
│   ├── ecs-cluster/   # one per env
│   ├── service/       # one per app+env (pulse, scout, ...)
│   ├── aurora/        # one per app+env (or shared cluster, multiple DBs)
│   └── efs/
└── envs/
    ├── prod/main.tf
    └── staging/main.tf
```

Approaches:

1. **Same ALB, host-based routing** — simplest. Each service registers a target
   group; ALB listener rule routes by `Host` header
   (`pulse.example.com` → pulse, `scout.example.com` → scout).
2. **Internal service discovery** — for service-to-service traffic without
   leaving the VPC, use **AWS Cloud Map** (`service.pulse.local`) attached to
   the ECS service. No internal ALB needed for simple HTTP fan-out.
3. **Internal ALB** — use when you need path-based routing or WAF on internal
   traffic. More expensive, more flexible.

IAM separation:

- Each app gets its own task role, e.g. `pulse-task-role` and
  `scout-task-role`. Secrets are namespaced (`pulse/prod/*`,
  `scout/prod/*`); each role can only read its own prefix.
- Each app gets its own GitHub OIDC role, scoped to its repo's
  `sub` claim, so a compromise of one repo can't deploy another app.

Database isolation options:

- **Separate Aurora cluster** per app (simplest, costs +$45/mo idle each).
- **One cluster, multiple databases** (`pulse`, `scout`) with per-app
  Postgres roles. Cheaper, but a runaway query in one app can starve the
  other — set `max_connections` and use `pg_stat_statements`.

Deployment:

- Copy `.github/workflows/deploy-aws.yml` to the new app's repo, change the
  `vars.ECS_SERVICE` / `vars.ECR_REPO` / `vars.RDS_CLUSTER_ID` values.
- The **same OIDC role** can be reused if you broaden its `iam:PassRole`
  resource to `arn:aws:iam::ACCT:role/{pulse,scout}-*`. Otherwise create one
  role per app for blast-radius reasons.

---

## Appendix A — Deploy workflow at a glance

```
push main ─┐
           ├─► lint  ─► build-push ─► deploy
manual run─┘                          │
                                      ├─ snapshot RDS
                                      ├─ aws ecs update-service --force-new-deployment
                                      ├─ aws ecs wait services-stable
                                      ├─ curl /api/health
                                      └─ on fail: rollback to previous task-def
```

Migrations run on **app boot**, guarded by a Postgres advisory lock (so
concurrent task starts are safe). Trade-off vs a separate `migrate` job:
faster pipeline, but a broken migration is only detected after the rolling
deploy starts — rollback path is the pre-deploy snapshot from §7.3.

## Appendix B — Required GitHub variables

| Scope             | Name                  | Purpose                                |
| ----------------- | --------------------- | -------------------------------------- |
| Env: staging,prod | `AWS_DEPLOY_ROLE_ARN` | OIDC role to assume                    |
| Env: staging,prod | `AWS_REGION`          | `us-east-1`                            |
| Env: staging,prod | `ECR_REPO`            | full ECR URI                           |
| Env: staging,prod | `ECS_CLUSTER`         | `pulse-<env>`                          |
| Env: staging,prod | `ECS_SERVICE`         | `pulse-api`                            |
| Env: staging,prod | `ALB_DNS`             | public DNS / hostname for smoke test   |
| Env: staging,prod | `RDS_CLUSTER_ID`      | `pulse-<env>`                          |

No long-lived AWS keys are stored in GitHub.
