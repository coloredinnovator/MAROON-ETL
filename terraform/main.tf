# MAROON-ETL Infrastructure
# AWS Account: 496411573616, us-west-2
# Budget: UNDER $0.10/month

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
  region = "us-west-2"

  default_tags {
    tags = {
      Project     = "MAROON-ETL"
      Environment = "production"
      ManagedBy   = "terraform"
      Budget      = "under-0.10-per-month"
    }
  }
}

# ─── S3: Main Data Lake Bucket ────────────────────────────────────────
resource "aws_s3_bucket" "datalake_main" {
  bucket = "maroon-datalake-496411573616-usw2"
}

resource "aws_s3_bucket_versioning" "datalake_main" {
  bucket = aws_s3_bucket.datalake_main.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "datalake_main" {
  bucket = aws_s3_bucket.datalake_main.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "datalake_main" {
  bucket = aws_s3_bucket.datalake_main.id

  rule {
    id     = "raw-to-glacier-90d"
    status = "Enabled"
    filter {
      prefix = "raw/"
    }
    transition {
      days          = 90
      storage_class = "GLACIER"
    }
    noncurrent_version_transition {
      noncurrent_days = 30
      storage_class   = "GLACIER"
    }
  }

  rule {
    id     = "manifests-to-ia-30d"
    status = "Enabled"
    filter {
      prefix = "_manifests/"
    }
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "datalake_main" {
  bucket = aws_s3_bucket.datalake_main.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ─── S3: Restricted Bucket (PII) ─────────────────────────────────────
resource "aws_s3_bucket" "datalake_restricted" {
  bucket = "maroon-datalake-restricted-496411573616-usw2"
}

resource "aws_s3_bucket_versioning" "datalake_restricted" {
  bucket = aws_s3_bucket.datalake_restricted.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "datalake_restricted" {
  bucket = aws_s3_bucket.datalake_restricted.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "datalake_restricted" {
  bucket = aws_s3_bucket.datalake_restricted.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ─── IAM: ETL Execution Role ─────────────────────────────────────────
resource "aws_iam_role" "etl_execution" {
  name = "maroon-etl-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRoleWithWebIdentity"
        Effect = "Allow"
        Principal = {
          Federated = "arn:aws:iam::496411573616:oidc-provider/token.actions.githubusercontent.com"
        }
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" = "repo:coloredinnovator/*:*"
          }
        }
      },
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

resource "aws_iam_role_policy" "etl_s3_access" {
  name = "maroon-etl-s3-access"
  role = aws_iam_role.etl_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:ListBucket",
          "s3:PutObjectTagging",
          "s3:GetObjectTagging",
          "s3:GetLifecycleConfiguration",
        ]
        Resource = [
          aws_s3_bucket.datalake_main.arn,
          "${aws_s3_bucket.datalake_main.arn}/*",
          aws_s3_bucket.datalake_restricted.arn,
          "${aws_s3_bucket.datalake_restricted.arn}/*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
        ]
        Resource = [
          "arn:aws:bedrock:us-west-2::foundation-model/deepseek.*",
        ]
      }
    ]
  })
}

# ─── Outputs ──────────────────────────────────────────────────────────
output "main_bucket_name" {
  value = aws_s3_bucket.datalake_main.id
}

output "restricted_bucket_name" {
  value = aws_s3_bucket.datalake_restricted.id
}

output "etl_role_arn" {
  value = aws_iam_role.etl_execution.arn
}
