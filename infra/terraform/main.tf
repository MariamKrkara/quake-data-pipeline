terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = var.project_name
      ManagedBy = "terraform"
    }
  }
}

# Latest official Ubuntu 24.04 LTS image published by Canonical.
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
}

data "aws_vpc" "default" {
  default = true
}

# Firewall: SSH only from your own IP. The database is never exposed.
resource "aws_security_group" "pipeline" {
  name        = "${var.project_name}-sg"
  description = "SSH from admin IP only"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ssh_cidr]
  }

  egress {
    description = "Outbound HTTPS to the USGS API, package mirrors and image registries"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_key_pair" "admin" {
  key_name   = "${var.project_name}-key"
  public_key = file(pathexpand(var.public_key_path))
}

resource "aws_instance" "pipeline" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  key_name               = aws_key_pair.admin.key_name
  vpc_security_group_ids = [aws_security_group.pipeline.id]

  # Installs Docker, clones the repo and starts the stack on first boot.
  user_data = templatefile("${path.module}/user_data.sh.tpl", {
    repo_url = var.repo_url
  })

  root_block_device {
    volume_type = "gp3"
    volume_size = 20
    encrypted   = true
  }

  # Require IMDSv2 (blocks a common credential-theft technique).
  metadata_options {
    http_tokens = "required"
  }

  tags = {
    Name = var.project_name
  }
}
