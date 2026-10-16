output "static_ip" {
  description = "Public IPv4 address of the server."
  value       = aws_lightsail_static_ip.app.ip_address
}

output "free_domain" {
  description = "Free address that points at the server (sslip.io); usable as SITE_DOMAIN."
  value       = "${replace(aws_lightsail_static_ip.app.ip_address, ".", "-")}.sslip.io"
}

output "ssh_command" {
  description = "How to log in."
  value       = "ssh ubuntu@${aws_lightsail_static_ip.app.ip_address}"
}

output "backup_bucket" {
  description = "Value for BACKUP_S3_BUCKET in the server .env."
  value       = aws_s3_bucket.backups.bucket
}

output "backup_iam_user" {
  description = "Create its access key by hand: aws iam create-access-key --user-name <this value>"
  value       = aws_iam_user.backup.name
}
