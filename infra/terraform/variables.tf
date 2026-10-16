variable "project" {
  description = "Name prefix for every resource."
  type        = string
  default     = "itsm"
}

variable "aws_region" {
  description = "AWS region. Tokyo keeps latency low for users in Japan."
  type        = string
  default     = "ap-northeast-1"
}

variable "availability_zone" {
  description = "Lightsail availability zone inside the region."
  type        = string
  default     = "ap-northeast-1a"
}

variable "bundle_id" {
  description = "Lightsail plan. micro_3_0 is the 1 GB, 2 vCPU plan with a public IPv4 address (USD 7 a month when this was written; check the current price first)."
  type        = string
  default     = "micro_3_0"
}

variable "blueprint_id" {
  description = "Operating system image."
  type        = string
  default     = "ubuntu_24_04"
}

variable "my_ip" {
  description = "Your public IPv4 address in CIDR form, for example 203.0.113.10/32. SSH (port 22) is open to this address only."
  type        = string

  validation {
    condition     = can(cidrhost(var.my_ip, 0)) && endswith(var.my_ip, "/32")
    error_message = "my_ip must be a single IPv4 address in CIDR form ending in /32, for example 203.0.113.10/32."
  }
}

variable "ssh_public_key_path" {
  description = "Path to the SSH public key that may log in as the ubuntu user."
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "backup_bucket_name" {
  description = "Globally unique S3 bucket name for database backups, for example itsm-backups-yourname-2026."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.backup_bucket_name))
    error_message = "Bucket names use 3 to 63 lowercase letters, digits, dots, or hyphens."
  }
}

variable "backup_prefix" {
  description = "Folder inside the bucket. Must match BACKUP_S3_PREFIX in the server .env."
  type        = string
  default     = "itsm"
}

variable "backup_retention_days" {
  description = "Backups older than this are deleted automatically."
  type        = number
  default     = 30
}

variable "alert_email" {
  description = "Address that receives the cost budget warnings."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alert_email))
    error_message = "alert_email must be an email address."
  }
}

variable "monthly_budget_usd" {
  description = "Monthly cost limit for the budget alert, in US dollars."
  type        = number
  default     = 10
}
