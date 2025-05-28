# main.tf
terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# Variables
variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "notification_email" {
  description = "Email for notifications"
  type        = string
  default     = "salman.naqvi@gmail.com"
}

variable "max_instances" {
  description = "Maximum number of EC2 instances in ASG"
  type        = number
  default     = 10
}

variable "app_domain" {
  description = "Domain name for the Flask app (used for HTTPS cert)"
  type        = string
  default     = "mobility.qolimpact.click"
}

variable "letsencrypt_email" {
  description = "Email for Let's Encrypt certificate registration"
  type        = string
  default     = "salman.naqvi@gmail.com"
}

variable "route53_zone_id" {
  description = "Route53 Hosted Zone ID for the domain (e.g., Z123456ABCDEFG)"
  type        = string
}

# Data sources
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# SNS Topic for notifications
resource "aws_sns_topic" "notifications" {
  name = "mobility-data-notifications"
}

resource "aws_sns_topic_subscription" "email_notification" {
  topic_arn = aws_sns_topic.notifications.arn
  protocol  = "email"
  endpoint  = var.notification_email
}

# VPC and networking (using default VPC for simplicity)
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Security Group for EC2 instances
resource "aws_security_group" "mobility_workers" {
  name_prefix = "mobility-workers-"
  vpc_id      = data.aws_vpc.default.id

  # Allow HTTP access
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Allow HTTPS access
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Allow Flask app port 5050
  ingress {
    from_port   = 5050
    to_port     = 5050
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Allow SSH access
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "mobility-workers"
  }
}

# IAM role for EC2 instances
resource "aws_iam_role" "ec2_mobility_role" {
  name = "EC2MobilityWorkerRole"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "ec2_mobility_policy" {
  name = "EC2MobilityWorkerPolicy"
  role = aws_iam_role.ec2_mobility_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::your-existing-bucket",
          "arn:aws:s3:::your-existing-bucket/*",
          "arn:aws:s3:::veraset-prd-platform-us-west-2",
          "arn:aws:s3:::veraset-prd-platform-us-west-2/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "sts:AssumeRole"
        ]
        Resource = "arn:aws:iam::651706782157:role/VerasetS3AccessRole"
      },
      {
        Effect = "Allow"
        Action = [
          "sns:Publish"
        ]
        Resource = aws_sns_topic.notifications.arn
      }
    ]
  })
}

resource "aws_iam_instance_profile" "ec2_mobility_profile" {
  name = "EC2MobilityWorkerProfile"
  role = aws_iam_role.ec2_mobility_role.name
}

# --- Secrets Manager for .env ---
resource "aws_secretsmanager_secret" "env_secret" {
  name                    = "mobility-data-lifecycle-env2"
  description             = ".env file for mobility-data-lifecycle-manager"
  recovery_window_in_days = 30
}

resource "aws_secretsmanager_secret_version" "env_secret_version" {
  secret_id     = aws_secretsmanager_secret.env_secret.id
  secret_string = "PLACEHOLDER_ENV_CONTENT" # Update this value after creation
}

# --- IAM Policy for EC2 to read secret ---
data "aws_iam_policy_document" "secretsmanager_access" {
  statement {
    actions = [
      "secretsmanager:GetSecretValue"
    ]
    resources = [aws_secretsmanager_secret.env_secret.arn]
  }
}

resource "aws_iam_role_policy" "ec2_secretsmanager_policy" {
  name   = "ec2-secretsmanager-policy"
  role   = aws_iam_role.ec2_mobility_role.id
  policy = data.aws_iam_policy_document.secretsmanager_access.json
}

# --- Single EC2 Instance using Launch Template ---
resource "aws_instance" "mobility_manager" {
  ami                    = "ami-09f4814ae750baed6" # Latest Amazon Linux 2 AMI for us-east-1
  instance_type          = "t3.micro"
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.mobility_workers.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2_mobility_profile.name
  user_data              = base64encode(templatefile("${path.module}/user_data.sh", {
    AWS_ENV_SECRET_NAME = aws_secretsmanager_secret.env_secret.name,
    AWS_REGION = var.aws_region,
    APP_DOMAIN = var.app_domain,
    LETSENCRYPT_EMAIL = var.letsencrypt_email
  }))
  key_name               = "salman-dev" # Use the salman-dev key pair for SSH access
  tags = {
    Name = "mobility-manager"
  }
}

# --- AWS Backup Plan for EC2 Instance ---
resource "aws_backup_vault" "mobility_backup_vault" {
  name = "mobility-ec2-backup-vault"
}

resource "aws_backup_plan" "mobility_backup_plan" {
  name = "mobility-ec2-daily-backup-plan"

  rule {
    rule_name         = "daily-backup"
    target_vault_name = aws_backup_vault.mobility_backup_vault.name
    schedule          = "cron(0 3 * * ? *)" # Daily at 3am UTC
    lifecycle {
      delete_after = 60 # Retain backups for 60 days
    }
  }
}

resource "aws_backup_selection" "mobility_backup_selection" {
  name         = "mobility-ec2-backup-selection"
  iam_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/service-role/AWSBackupDefaultServiceRole"
  plan_id      = aws_backup_plan.mobility_backup_plan.id

  resources = [aws_instance.mobility_manager.arn]
}

# --- Outputs for EC2 Instance ---
output "ec2_instance_id" {
  description = "EC2 Instance ID"
  value       = aws_instance.mobility_manager.id
}

output "ec2_public_ip" {
  description = "EC2 Public IP"
  value       = aws_instance.mobility_manager.public_ip
}

output "ec2_private_ip" {
  description = "EC2 Private IP"
  value       = aws_instance.mobility_manager.private_ip
}

# --- CloudWatch Alarm for EC2 Instance Status Check Failure ---
resource "aws_cloudwatch_metric_alarm" "ec2_status_check_failed" {
  alarm_name          = "mobility-ec2-status-check-failed"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "StatusCheckFailed"
  namespace           = "AWS/EC2"
  period              = "60"
  statistic           = "Average"
  threshold           = "0"
  alarm_description   = "Alarm if EC2 instance status check fails"
  alarm_actions       = [aws_sns_topic.notifications.arn]

  dimensions = {
    InstanceId = aws_instance.mobility_manager.id
  }
}

# --- CloudWatch Alarm for AWS Backup Job Failures ---
resource "aws_cloudwatch_metric_alarm" "backup_job_failed" {
  alarm_name          = "mobility-backup-job-failed"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "NumberOfBackupJobsFailed"
  namespace           = "AWS/Backup"
  period              = "300"
  statistic           = "Sum"
  threshold           = "0"
  alarm_description   = "Alarm if any backup job fails in the backup vault"
  alarm_actions       = [aws_sns_topic.notifications.arn]

  dimensions = {
    BackupVaultName = aws_backup_vault.mobility_backup_vault.name
  }
}

output "app_url" {
  description = "HTTPS URL for the Flask app"
  value       = "https://${var.app_domain}"
}

resource "aws_route53_record" "app" {
  zone_id = var.route53_zone_id
  name    = var.app_domain
  type    = "A"
  ttl     = 300
  records = [aws_instance.mobility_manager.public_ip]
}

output "app_dns_record" {
  description = "Route53 record for the app domain"
  value       = aws_route53_record.app.fqdn
}