variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "eu-central-1"
}

variable "project_name" {
  description = "Prefix used for resource names and tags"
  type        = string
  default     = "quake-pipeline"
}

variable "instance_type" {
  description = "EC2 instance size"
  type        = string
  default     = "t3.micro"
}

variable "allowed_ssh_cidr" {
  description = "Your public IP in CIDR form, e.g. 41.208.10.20/32"
  type        = string
}

variable "public_key_path" {
  description = "Path to the SSH public key used to log in to the instance"
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "repo_url" {
  description = "Public Git URL of this repository"
  type        = string
  default     = "https://github.com/MariamKrkara/quake-data-pipeline.git"
}
