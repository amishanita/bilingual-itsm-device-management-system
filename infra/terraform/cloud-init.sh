#!/bin/bash
# First-boot setup for the Lightsail server. Lightsail runs this once, as root,
# when the instance is created. Output goes to /var/log/cloud-init-output.log.
#
# It prepares the machine only; the application is deployed afterwards by hand
# (git clone, .env, docker compose up) as described in docs/構築手順書.md.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# Japan time, so cron times and log timestamps read naturally.
timedatectl set-timezone Asia/Tokyo

# 1 GB swap: the 1 GB plan can run out of memory while Docker builds the API image.
if [ ! -f /swapfile ]; then
	fallocate -l 1G /swapfile
	chmod 600 /swapfile
	mkswap /swapfile
	swapon /swapfile
	echo "/swapfile none swap sw 0 0" >>/etc/fstab
	echo "vm.swappiness=10" >/etc/sysctl.d/99-swappiness.conf
	sysctl -p /etc/sysctl.d/99-swappiness.conf
fi

# Security updates install themselves (Ubuntu's unattended-upgrades).
apt-get update
apt-get install -y ca-certificates curl git unattended-upgrades
dpkg-reconfigure -f noninteractive unattended-upgrades

# Docker Engine and the Compose plugin from Docker's own apt repository.
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
codename=$(grep -oP "^VERSION_CODENAME=\K.*" /etc/os-release)
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${codename} stable" \
	>/etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

# AWS CLI v2, used by the backup scripts.
snap install aws-cli --classic

# Let the ubuntu user run docker without sudo, and give cron jobs a log folder.
usermod -aG docker ubuntu
install -d -o ubuntu -g ubuntu /home/ubuntu/itsm-logs

echo "itsm bootstrap finished"
