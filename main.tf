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

variable "s3_bucket_name" {
  description = "S3 bucket for mobility data"
  type        = string
  default     = "veraset-data-qoli-dev"
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

# Data sources
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# S3 Bucket for mobility data with lifecycle policy
resource "aws_s3_bucket" "mobility_data" {
  bucket = var.s3_bucket_name
}

resource "aws_s3_bucket_lifecycle_configuration" "mobility_data_lifecycle" {
  bucket = aws_s3_bucket.mobility_data.id

  rule {
    id     = "delete_old_mobility_data"
    status = "Enabled"

    expiration {
      days = 7
    }

    filter {
      prefix = "data/"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "mobility_data_pab" {
  bucket = aws_s3_bucket.mobility_data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# SNS Topic for notifications
resource "aws_sns_topic" "notifications" {
  name = "mobility-data-notifications"
}

resource "aws_sns_topic_subscription" "email_notification" {
  topic_arn = aws_sns_topic.notifications.arn
  protocol  = "email"
  endpoint  = var.notification_email
}

# SQS Queue for job distribution
resource "aws_sqs_queue" "job_queue" {
  name                       = "mobility-job-queue"
  visibility_timeout_seconds = 7200  # 2 hours
  message_retention_seconds  = 1209600  # 14 days

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3
  })
}

# Dead Letter Queue
resource "aws_sqs_queue" "dlq" {
  name = "mobility-job-dlq"
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
          aws_s3_bucket.mobility_data.arn,
          "${aws_s3_bucket.mobility_data.arn}/*",
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
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = aws_sqs_queue.job_queue.arn
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

# Launch template for EC2 instances
resource "aws_launch_template" "mobility_worker" {
  name_prefix   = "mobility-worker-"
  image_id      = "ami-0c02fb55956c7d316"  # Amazon Linux 2 AMI (update for your region)
  instance_type = "t3.micro"

  vpc_security_group_ids = [aws_security_group.mobility_workers.id]

  iam_instance_profile {
    name = aws_iam_instance_profile.ec2_mobility_profile.name
  }

  user_data = base64encode(templatefile("${path.module}/user_data.sh", {
    s3_bucket = aws_s3_bucket.mobility_data.id
    queue_url = aws_sqs_queue.job_queue.url
    region    = var.aws_region
  }))

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name = "mobility-worker"
    }
  }
}

# Auto Scaling Group
resource "aws_autoscaling_group" "mobility_workers" {
  name                = "mobility-workers-asg"
  vpc_zone_identifier = data.aws_subnets.default.ids
  target_group_arns   = []
  health_check_type   = "EC2"
  
  min_size         = 0
  max_size         = var.max_instances
  desired_capacity = 0

  launch_template {
    id      = aws_launch_template.mobility_worker.id
    version = "$Latest"
  }

  tag {
    key                 = "Name"
    value               = "mobility-worker"
    propagate_at_launch = false
  }
}

# CloudWatch metric for SQS queue
resource "aws_cloudwatch_metric_alarm" "sqs_scale_up" {
  alarm_name          = "mobility-sqs-scale-up"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "ApproximateNumberOfVisibleMessages"
  namespace           = "AWS/SQS"
  period              = "120"
  statistic           = "Average"
  threshold           = "5"
  alarm_description   = "This metric monitors sqs queue depth"
  alarm_actions       = [aws_autoscaling_policy.scale_up.arn]

  dimensions = {
    QueueName = aws_sqs_queue.job_queue.name
  }
}

resource "aws_cloudwatch_metric_alarm" "sqs_scale_down" {
  alarm_name          = "mobility-sqs-scale-down"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "ApproximateNumberOfVisibleMessages"
  namespace           = "AWS/SQS"
  period              = "300"
  statistic           = "Average"
  threshold           = "1"
  alarm_description   = "This metric monitors sqs queue depth"
  alarm_actions       = [aws_autoscaling_policy.scale_down.arn]

  dimensions = {
    QueueName = aws_sqs_queue.job_queue.name
  }
}

# Auto Scaling Policies
resource "aws_autoscaling_policy" "scale_up" {
  name                   = "mobility-scale-up"
  scaling_adjustment     = 2
  adjustment_type        = "ChangeInCapacity"
  cooldown               = 300
  autoscaling_group_name = aws_autoscaling_group.mobility_workers.name
}

resource "aws_autoscaling_policy" "scale_down" {
  name                   = "mobility-scale-down"
  scaling_adjustment     = -1
  adjustment_type        = "ChangeInCapacity"
  cooldown               = 300
  autoscaling_group_name = aws_autoscaling_group.mobility_workers.name
}

# IAM role for Lambda
resource "aws_iam_role" "lambda_orchestrator_role" {
  name = "MobilityLambdaOrchestratorRole"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "lambda_orchestrator_policy" {
  name = "MobilityLambdaOrchestratorPolicy"
  role = aws_iam_role.lambda_orchestrator_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = aws_sqs_queue.job_queue.arn
      },
      {
        Effect = "Allow"
        Action = [
          "sns:Publish"
        ]
        Resource = aws_sns_topic.notifications.arn
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject"
        ]
        Resource = [
          "${aws_s3_bucket.mobility_data.arn}/*"
        ]
      }
    ]
  })
}

# Lambda function
resource "aws_lambda_function" "orchestrator" {
  filename         = "orchestrator.zip"
  function_name    = "mobility-data-orchestrator"
  role            = aws_iam_role.lambda_orchestrator_role.arn
  handler         = "orchestrator.lambda_handler"
  runtime         = "python3.9"
  timeout         = 900  # 15 minutes

  environment {
    variables = {
      CITIES_TABLE = aws_dynamodb_table.cities_config.name
      JOB_TRACKING_TABLE = aws_dynamodb_table.job_tracking.name
      NOTIFICATION_TABLE = aws_dynamodb_table.notification_config.name
      SQS_QUEUE_URL = aws_sqs_queue.job_queue.url
      SNS_TOPIC_ARN = aws_sns_topic.notifications.arn
      S3_BUCKET = aws_s3_bucket.mobility_data.id
    }
  }

  depends_on = [
    aws_iam_role_policy.lambda_orchestrator_policy,
  ]
}

# EventBridge rule for daily execution
resource "aws_cloudwatch_event_rule" "daily_trigger" {
  name                = "mobility-daily-trigger"
  description         = "Trigger mobility data collection daily at 2 AM UTC"
  schedule_expression = "cron(0 2 * * ? *)"
}

resource "aws_cloudwatch_event_target" "lambda_target" {
  rule      = aws_cloudwatch_event_rule.daily_trigger.name
  target_id = "MobilityLambdaTarget"
  arn       = aws_lambda_function.orchestrator.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.orchestrator.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_trigger.arn
}

# Outputs
output "s3_bucket_name" {
  value = aws_s3_bucket.mobility_data.id
}

output "sqs_queue_url" {
  value = aws_sqs_queue.job_queue.url
}

output "lambda_function_name" {
  value = aws_lambda_function.orchestrator.function_name
}