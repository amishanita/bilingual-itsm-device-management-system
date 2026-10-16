# Infrastructure (Terraform)

Creates the AWS resources for the public demo in the Tokyo region:

| Resource | Purpose |
| --- | --- |
| Lightsail instance (Ubuntu 24.04, 1 GB plan) | Runs `docker-compose.prod.yml` |
| Lightsail static IP | Address that survives restarts; also gives a free `x-x-x-x.sslip.io` domain |
| Lightsail firewall | 80 and 443 open to everyone, 22 open only to `my_ip` |
| S3 bucket | Database backups: private, encrypted, HTTPS only, deleted after 30 days |
| IAM user `itsm-backup` | Can upload, read, and list backups under the prefix. Cannot delete. |
| AWS Budget | Emails a warning when the month's bill is heading past the limit |

The first-boot script `cloud-init.sh` sets the time zone to Asia/Tokyo, adds 1 GB of swap,
turns on automatic security updates, and installs Docker, the Compose plugin, and the AWS CLI.
Deploying the application itself is a separate step (see `docs/構築手順書.md`).

## Cost

Check the current prices before running `apply`; the figures below were read from the AWS
pricing pages in October 2026 and can change.

- Lightsail 1 GB plan with public IPv4: USD 7 per month (2 vCPU, 40 GB SSD, 2 TB transfer).
  The static IP is free while it is attached to a running instance.
- S3: a few MB of compressed dumps, well under USD 0.10 per month.
- Budgets: the first two budgets in an account are free.

Whether any of this falls under the AWS Free Tier depends on how old the account is and which
Free Tier plan it is on. Check **Billing and Cost Management > Free Tier** in the console rather
than assuming it.

## Before the first run

1. Install Terraform and the AWS CLI (macOS):

   ```bash
   brew tap hashicorp/tap && brew install hashicorp/tap/terraform
   brew install awscli
   ```

2. Sign in with an IAM user or SSO profile that can manage Lightsail, S3, IAM, and Budgets
   (not the root account): `aws configure` or `aws configure sso`.

3. Confirm the plan and image IDs still exist, because AWS retires old ones:

   ```bash
   aws lightsail get-bundles --region ap-northeast-1 \
     --query "bundles[?bundleId=='micro_3_0'].[bundleId,price,ramSizeInGb,isActive]"
   aws lightsail get-blueprints --region ap-northeast-1 \
     --query "blueprints[?blueprintId=='ubuntu_24_04'].[blueprintId,name,isActive]"
   ```

   If either comes back empty, set `bundle_id` or `blueprint_id` in `terraform.tfvars` to the
   current ID.

4. Create the variables file and fill it in:

   ```bash
   cp terraform.tfvars.example terraform.tfvars
   curl -s https://checkip.amazonaws.com    # your IP for my_ip, add /32
   ```

   An SSH key is needed at `~/.ssh/id_ed25519.pub` (create one with `ssh-keygen -t ed25519`).

## Run

```bash
terraform init
terraform fmt -check
terraform validate
terraform plan -out=tfplan     # read the plan: expect 14 resources to add, 0 to change or destroy
terraform apply tfplan
```

Budget emails go straight to `alert_email` with no confirmation step. Mark the first one as
"not spam" if it lands there.

## After apply

1. Create the backup access key by hand, so the secret never enters the Terraform state:

   ```bash
   aws iam create-access-key --user-name "$(terraform output -raw backup_iam_user)"
   ```

   Put the two values in `/home/ubuntu/.aws/credentials` on the server (profile `default`),
   with permissions `600`. Do not paste them into `.env`, Git, or chat.

2. Check the firewall really is what the code says. Port 22 should list only your IPv4 address
   and no IPv6 range:

   ```bash
   aws lightsail get-instance-port-states --instance-name itsm-app --region ap-northeast-1
   ```

3. Ask AWS's policy simulator what the backup user may do. Expected: the first two lines
   `allowed`, the other three `implicitDeny`.

   ```bash
   USER_ARN=$(aws iam get-user --user-name itsm-backup --query User.Arn --output text)
   B=$(terraform output -raw backup_bucket)
   sim() { aws iam simulate-principal-policy --policy-source-arn "$USER_ARN" "$@" \
     --query "EvaluationResults[0].[EvalActionName,EvalDecision]" --output text; }
   sim --action-names s3:PutObject  --resource-arns "arn:aws:s3:::$B/itsm/test.sql.gz"
   sim --action-names s3:ListBucket --resource-arns "arn:aws:s3:::$B" \
     --context-entries "ContextKeyName=s3:prefix,ContextKeyValues=itsm/,ContextKeyType=string"
   sim --action-names s3:DeleteObject --resource-arns "arn:aws:s3:::$B/itsm/test.sql.gz"
   sim --action-names s3:PutObject  --resource-arns "arn:aws:s3:::$B/other/x"
   sim --action-names s3:ListBucket --resource-arns "arn:aws:s3:::$B"
   ```

4. Wait two or three minutes for first boot, then log in and confirm the setup finished:

   ```bash
   $(terraform output -raw ssh_command)
   tail -n 3 /var/log/cloud-init-output.log     # last line: itsm bootstrap finished
   docker compose version && aws --version && timedatectl | grep "Time zone"
   ```

5. Use `terraform output -raw free_domain` as `SITE_DOMAIN` and
   `terraform output -raw backup_bucket` as `BACKUP_S3_BUCKET` in the server's `.env`.

## When your IP changes

SSH stops working when your home IP changes. Update `my_ip` in `terraform.tfvars` and run
`terraform apply`; only the firewall rules change.

## State

State is stored locally in `terraform.tfstate`, which Git ignores. It holds resource IDs, the
SSH public key, and the alert email, but no passwords or access keys. Keep a copy somewhere safe:
without it, Terraform cannot manage or remove these resources. For a team, move it to an S3
backend with locking.

## Removing everything

```bash
terraform destroy
```

The backup bucket is not emptied automatically, so `destroy` stops at the bucket while it still
holds backups. That is on purpose; empty it in the console first if you really mean to delete
the backups.
