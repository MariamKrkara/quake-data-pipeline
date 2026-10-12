#!/bin/bash
# Runs once, as root, on the instance's first boot.
set -euxo pipefail

apt-get update
apt-get install -y docker.io docker-compose-v2 git
systemctl enable --now docker
usermod -aG docker ubuntu

git clone ${repo_url} /opt/quake-data-pipeline
cd /opt/quake-data-pipeline

# Generate the database password on the server, so it never appears in
# Terraform state or in the repository.
cp .env.example .env
sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(openssl rand -hex 24)/" .env
chmod 600 .env
chown -R ubuntu:ubuntu /opt/quake-data-pipeline

docker compose up -d --build
