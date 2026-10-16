# Infrastructure for the public demo:
#   - one Lightsail instance (Ubuntu) with a static IP
#   - a firewall: 80 and 443 for everyone, 22 only from my_ip
#   - an S3 bucket for database backups (private, encrypted, 30-day expiry)
#   - an IAM user that can only put and read backups in that bucket
#   - a monthly cost budget that emails a warning
#
# The application itself is deployed by the steps in docs/構築手順書.md.

locals {
  name = var.project
}

# Server

resource "aws_lightsail_key_pair" "admin" {
  name       = "${local.name}-admin"
  public_key = file(pathexpand(var.ssh_public_key_path))
}

resource "aws_lightsail_instance" "app" {
  name              = "${local.name}-app"
  availability_zone = var.availability_zone
  blueprint_id      = var.blueprint_id
  bundle_id         = var.bundle_id
  key_pair_name     = aws_lightsail_key_pair.admin.name
  # First-boot setup: time zone, swap, Docker, AWS CLI. See cloud-init.sh.
  user_data = file("${path.module}/cloud-init.sh")

  lifecycle {
    # Changing user_data would replace the server and delete the database on
    # it. The script only matters on first boot, so later edits are ignored.
    ignore_changes = [user_data]
  }
}

resource "aws_lightsail_static_ip" "app" {
  name = "${local.name}-ip"
}

resource "aws_lightsail_static_ip_attachment" "app" {
  static_ip_name = aws_lightsail_static_ip.app.name
  instance_name  = aws_lightsail_instance.app.name
}

# This resource replaces Lightsail's default firewall, which opens SSH to the
# whole internet. Only the ports listed here stay open.
resource "aws_lightsail_instance_public_ports" "app" {
  instance_name = aws_lightsail_instance.app.name

  port_info {
    protocol   = "tcp"
    from_port  = 80
    to_port    = 80
    cidrs      = ["0.0.0.0/0"]
    ipv6_cidrs = ["::/0"]
  }

  port_info {
    protocol   = "tcp"
    from_port  = 443
    to_port    = 443
    cidrs      = ["0.0.0.0/0"]
    ipv6_cidrs = ["::/0"]
  }

  # HTTP/3 (QUIC) for browsers that support it; Caddy serves it on UDP 443.
  port_info {
    protocol   = "udp"
    from_port  = 443
    to_port    = 443
    cidrs      = ["0.0.0.0/0"]
    ipv6_cidrs = ["::/0"]
  }

  port_info {
    protocol  = "tcp"
    from_port = 22
    to_port   = 22
    cidrs     = [var.my_ip]
  }
}

# Backups

resource "aws_s3_bucket" "backups" {
  bucket = var.backup_bucket_name
}

resource "aws_s3_bucket_public_access_block" "backups" {
  bucket                  = aws_s3_bucket.backups.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id

  rule {
    id     = "expire-old-backups"
    status = "Enabled"

    filter {
      prefix = "${var.backup_prefix}/"
    }

    expiration {
      days = var.backup_retention_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

# Refuse any request that is not over HTTPS.
resource "aws_s3_bucket_policy" "backups" {
  bucket = aws_s3_bucket.backups.id
  policy = data.aws_iam_policy_document.backups_bucket.json

  depends_on = [aws_s3_bucket_public_access_block.backups]
}

data "aws_iam_policy_document" "backups_bucket" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.backups.arn,
      "${aws_s3_bucket.backups.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

# Backup credentials

# Lightsail instances cannot use IAM roles, so the server uses an access key
# for this user. The key is created by hand (see README.md) so the secret never
# lands in the Terraform state file.
resource "aws_iam_user" "backup" {
  name = "${local.name}-backup"
}

# Upload and read backups under the prefix, and list them. No delete: a
# compromised server cannot erase the backup history (old files expire through
# the lifecycle rule instead).
data "aws_iam_policy_document" "backup_user" {
  statement {
    sid       = "PutAndReadBackups"
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${aws_s3_bucket.backups.arn}/${var.backup_prefix}/*"]
  }

  statement {
    sid       = "ListBackups"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.backups.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${var.backup_prefix}/*"]
    }
  }
}

resource "aws_iam_user_policy" "backup" {
  name   = "${local.name}-backup-bucket-only"
  user   = aws_iam_user.backup.name
  policy = data.aws_iam_policy_document.backup_user.json
}

# Cost guard

# Email alerts when this month's AWS bill is forecast to pass 80% of the limit,
# and again when it actually passes it. Covers the whole account, not only
# these resources. AWS does not charge for the first two budgets.
resource "aws_budgets_budget" "monthly" {
  name         = "${local.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
}
