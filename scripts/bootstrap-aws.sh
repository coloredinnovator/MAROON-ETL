#!/bin/bash
# =============================================================================
# MAROON + SHAFANNA AWS Bootstrap Script
# Run this in AWS CloudShell (us-west-2) to provision all infrastructure.
#
# Prerequisites:
#   - AWS CloudShell (pre-authenticated with admin/poweruser credentials)
#   - Region: us-west-2
#
# This script is IDEMPOTENT - safe to run multiple times.
# Budget target: under $0.10/month (all pay-per-use / free tier resources)
# =============================================================================

set -euo pipefail

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
AWS_REGION="us-west-2"
AWS_ACCOUNT_ID="496411573616"

# S3 Buckets
MAIN_BUCKET="maroon-datalake-${AWS_ACCOUNT_ID}-usw2"
RESTRICTED_BUCKET="maroon-datalake-restricted-${AWS_ACCOUNT_ID}-usw2"
SHAFANNA_BUCKET="shafanna-datalake-${AWS_ACCOUNT_ID}"

# DynamoDB
DYNAMO_TABLE="shafanna-agent-memory"

# OIDC
OIDC_URL="https://token.actions.githubusercontent.com"
OIDC_THUMBPRINT="6938fd4d98bab03faadb97b34396831e3780aea1"
OIDC_AUDIENCE="sts.amazonaws.com"

# IAM Roles
SHAFANNA_ROLE="shafanna-github-actions"
ETL_ROLE="maroon-etl-github-actions"

# ECR
ECR_REPO="shafanna-etl"

# GitHub repos for OIDC trust
SHAFANNA_REPO="coloredinnovator/Maroon-Shevette-master-agent"
MAROON_TECHO_REPO="maroon-techo/*"
ETL_REPO="coloredinnovator/MAROON-ETL"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------
info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }
step()  { echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; echo -e "${BLUE}  STEP: $*${NC}"; echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }

# Verify we are in the right account and region
verify_environment() {
    step "Verifying AWS environment"

    local caller_id
    caller_id=$(aws sts get-caller-identity --query "Account" --output text 2>/dev/null) || \
        fail "Cannot call sts:GetCallerIdentity. Are you in AWS CloudShell?"

    if [ "$caller_id" != "$AWS_ACCOUNT_ID" ]; then
        fail "Expected account ${AWS_ACCOUNT_ID}, got ${caller_id}. Switch to the correct account."
    fi
    ok "Account: ${AWS_ACCOUNT_ID}"

    # Force region
    export AWS_DEFAULT_REGION="${AWS_REGION}"
    export AWS_REGION="${AWS_REGION}"
    ok "Region: ${AWS_REGION}"

    local identity
    identity=$(aws sts get-caller-identity --query "Arn" --output text)
    ok "Identity: ${identity}"
}

# -----------------------------------------------------------------------------
# Step 1: S3 Buckets
# -----------------------------------------------------------------------------
create_bucket() {
    local bucket_name="$1"
    local description="$2"

    if aws s3api head-bucket --bucket "$bucket_name" 2>/dev/null; then
        ok "Bucket already exists: ${bucket_name}"
    else
        info "Creating bucket: ${bucket_name} (${description})"
        aws s3api create-bucket \
            --bucket "$bucket_name" \
            --region "$AWS_REGION" \
            --create-bucket-configuration LocationConstraint="$AWS_REGION" \
            --output text > /dev/null
        ok "Created bucket: ${bucket_name}"
    fi

    # Enable versioning
    aws s3api put-bucket-versioning \
        --bucket "$bucket_name" \
        --versioning-configuration Status=Enabled
    ok "  Versioning enabled"

    # Enable SSE-S3 encryption
    aws s3api put-bucket-encryption \
        --bucket "$bucket_name" \
        --server-side-encryption-configuration '{
            "Rules": [{
                "ApplyServerSideEncryptionByDefault": {
                    "SSEAlgorithm": "AES256"
                },
                "BucketKeyEnabled": true
            }]
        }'
    ok "  SSE-S3 encryption enabled"

    # Block all public access
    aws s3api put-public-access-block \
        --bucket "$bucket_name" \
        --public-access-block-configuration \
            "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
    ok "  Public access blocked"
}

create_s3_buckets() {
    step "Creating S3 Buckets"

    create_bucket "$MAIN_BUCKET" "main data lake"
    create_bucket "$RESTRICTED_BUCKET" "PII-restricted data"
    create_bucket "$SHAFANNA_BUCKET" "Shafanna agent bucket"

    # Add lifecycle rule to main bucket (raw/ to Glacier after 90 days)
    info "Adding lifecycle rule to ${MAIN_BUCKET} (raw/ -> Glacier at 90d)"
    aws s3api put-bucket-lifecycle-configuration \
        --bucket "$MAIN_BUCKET" \
        --lifecycle-configuration '{
            "Rules": [{
                "ID": "raw-to-glacier-90d",
                "Status": "Enabled",
                "Filter": {
                    "Prefix": "raw/"
                },
                "Transitions": [{
                    "Days": 90,
                    "StorageClass": "GLACIER"
                }]
            }]
        }'
    ok "  Lifecycle rule: raw/ -> Glacier after 90 days"
}

# -----------------------------------------------------------------------------
# Step 2: DynamoDB Table
# -----------------------------------------------------------------------------
create_dynamodb_table() {
    step "Creating DynamoDB Table"

    local table_exists
    table_exists=$(aws dynamodb describe-table --table-name "$DYNAMO_TABLE" --query "Table.TableName" --output text 2>/dev/null || echo "NONE")

    if [ "$table_exists" = "$DYNAMO_TABLE" ]; then
        ok "Table already exists: ${DYNAMO_TABLE}"
    else
        info "Creating table: ${DYNAMO_TABLE}"
        aws dynamodb create-table \
            --table-name "$DYNAMO_TABLE" \
            --attribute-definitions \
                AttributeName=pk,AttributeType=S \
                AttributeName=sk,AttributeType=S \
            --key-schema \
                AttributeName=pk,KeyType=HASH \
                AttributeName=sk,KeyType=RANGE \
            --billing-mode PAY_PER_REQUEST \
            --region "$AWS_REGION" \
            --output text > /dev/null
        ok "Created table: ${DYNAMO_TABLE}"

        # Wait for table to become active
        info "Waiting for table to become ACTIVE..."
        aws dynamodb wait table-exists --table-name "$DYNAMO_TABLE"
        ok "Table is ACTIVE"
    fi

    # Enable TTL
    local ttl_status
    ttl_status=$(aws dynamodb describe-time-to-live --table-name "$DYNAMO_TABLE" --query "TimeToLiveDescription.TimeToLiveStatus" --output text 2>/dev/null || echo "DISABLED")

    if [ "$ttl_status" = "ENABLED" ]; then
        ok "TTL already enabled"
    else
        info "Enabling TTL on attribute 'ttl'"
        aws dynamodb update-time-to-live \
            --table-name "$DYNAMO_TABLE" \
            --time-to-live-specification "Enabled=true,AttributeName=ttl" \
            --output text > /dev/null 2>&1 || true
        ok "TTL enabled (attribute: ttl)"
    fi
}

# -----------------------------------------------------------------------------
# Step 3: OIDC Provider
# -----------------------------------------------------------------------------
create_oidc_provider() {
    step "Creating GitHub Actions OIDC Provider"

    local oidc_arn="arn:aws:iam::${AWS_ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"

    # Check if it already exists
    if aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$oidc_arn" > /dev/null 2>&1; then
        ok "OIDC provider already exists"
    else
        info "Creating OIDC provider for GitHub Actions"
        aws iam create-open-id-connect-provider \
            --url "$OIDC_URL" \
            --client-id-list "$OIDC_AUDIENCE" \
            --thumbprint-list "$OIDC_THUMBPRINT" \
            --output text > /dev/null
        ok "OIDC provider created: ${OIDC_URL}"
    fi
}

# -----------------------------------------------------------------------------
# Step 4: IAM Roles
# -----------------------------------------------------------------------------
create_shafanna_role() {
    step "Creating IAM Role: ${SHAFANNA_ROLE}"

    local oidc_arn="arn:aws:iam::${AWS_ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"

    # Trust policy allowing GitHub OIDC from specified repos
    local trust_policy
    trust_policy=$(cat <<EOF
{
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {
            "Federated": "${oidc_arn}"
        },
        "Action": "sts:AssumeRoleWithWebIdentity",
        "Condition": {
            "StringEquals": {
                "token.actions.githubusercontent.com:aud": "${OIDC_AUDIENCE}"
            },
            "StringLike": {
                "token.actions.githubusercontent.com:sub": [
                    "repo:${SHAFANNA_REPO}:*",
                    "repo:${MAROON_TECHO_REPO}:*"
                ]
            }
        }
    }]
}
EOF
)

    if aws iam get-role --role-name "$SHAFANNA_ROLE" > /dev/null 2>&1; then
        ok "Role already exists: ${SHAFANNA_ROLE}"
        info "Updating trust policy..."
        aws iam update-assume-role-policy \
            --role-name "$SHAFANNA_ROLE" \
            --policy-document "$trust_policy"
        ok "Trust policy updated"
    else
        info "Creating role: ${SHAFANNA_ROLE}"
        aws iam create-role \
            --role-name "$SHAFANNA_ROLE" \
            --assume-role-policy-document "$trust_policy" \
            --description "GitHub Actions OIDC role for Shafanna master agent" \
            --output text > /dev/null
        ok "Role created: ${SHAFANNA_ROLE}"
    fi
}

create_etl_role() {
    step "Creating IAM Role: ${ETL_ROLE}"

    local oidc_arn="arn:aws:iam::${AWS_ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"

    local trust_policy
    trust_policy=$(cat <<EOF
{
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {
            "Federated": "${oidc_arn}"
        },
        "Action": "sts:AssumeRoleWithWebIdentity",
        "Condition": {
            "StringEquals": {
                "token.actions.githubusercontent.com:aud": "${OIDC_AUDIENCE}"
            },
            "StringLike": {
                "token.actions.githubusercontent.com:sub": "repo:${ETL_REPO}:*"
            }
        }
    }]
}
EOF
)

    if aws iam get-role --role-name "$ETL_ROLE" > /dev/null 2>&1; then
        ok "Role already exists: ${ETL_ROLE}"
        info "Updating trust policy..."
        aws iam update-assume-role-policy \
            --role-name "$ETL_ROLE" \
            --policy-document "$trust_policy"
        ok "Trust policy updated"
    else
        info "Creating role: ${ETL_ROLE}"
        aws iam create-role \
            --role-name "$ETL_ROLE" \
            --assume-role-policy-document "$trust_policy" \
            --description "GitHub Actions OIDC role for MAROON-ETL pipeline" \
            --output text > /dev/null
        ok "Role created: ${ETL_ROLE}"
    fi
}

# -----------------------------------------------------------------------------
# Step 5: IAM Policies
# -----------------------------------------------------------------------------
attach_shafanna_policies() {
    step "Attaching policies to ${SHAFANNA_ROLE}"

    local policy_name="shafanna-github-actions-policy"
    local policy_arn="arn:aws:iam::${AWS_ACCOUNT_ID}:policy/${policy_name}"

    local policy_doc
    policy_doc=$(cat <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "S3DataLakeAccess",
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:GetObject",
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::${MAIN_BUCKET}",
                "arn:aws:s3:::${MAIN_BUCKET}/*",
                "arn:aws:s3:::${RESTRICTED_BUCKET}",
                "arn:aws:s3:::${RESTRICTED_BUCKET}/*",
                "arn:aws:s3:::${SHAFANNA_BUCKET}",
                "arn:aws:s3:::${SHAFANNA_BUCKET}/*"
            ]
        },
        {
            "Sid": "DynamoDBAgentMemory",
            "Effect": "Allow",
            "Action": [
                "dynamodb:GetItem",
                "dynamodb:PutItem",
                "dynamodb:Query",
                "dynamodb:UpdateItem"
            ],
            "Resource": "arn:aws:dynamodb:${AWS_REGION}:${AWS_ACCOUNT_ID}:table/${DYNAMO_TABLE}"
        },
        {
            "Sid": "BedrockDeepSeek",
            "Effect": "Allow",
            "Action": "bedrock:InvokeModel",
            "Resource": "arn:aws:bedrock:${AWS_REGION}::foundation-model/deepseek.*"
        },
        {
            "Sid": "ECRAccess",
            "Effect": "Allow",
            "Action": [
                "ecr:GetAuthorizationToken",
                "ecr:BatchCheckLayerAvailability",
                "ecr:GetDownloadUrlForLayer",
                "ecr:BatchGetImage",
                "ecr:PutImage",
                "ecr:InitiateLayerUpload",
                "ecr:UploadLayerPart",
                "ecr:CompleteLayerUpload"
            ],
            "Resource": "arn:aws:ecr:${AWS_REGION}:${AWS_ACCOUNT_ID}:repository/${ECR_REPO}"
        },
        {
            "Sid": "ECRAuth",
            "Effect": "Allow",
            "Action": "ecr:GetAuthorizationToken",
            "Resource": "*"
        },
        {
            "Sid": "CloudWatchLogs",
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents",
                "logs:DescribeLogGroups",
                "logs:DescribeLogStreams"
            ],
            "Resource": "arn:aws:logs:${AWS_REGION}:${AWS_ACCOUNT_ID}:log-group:/maroon/*"
        }
    ]
}
EOF
)

    # Create or update the policy
    if aws iam get-policy --policy-arn "$policy_arn" > /dev/null 2>&1; then
        ok "Policy exists: ${policy_name}"
        info "Creating new policy version..."
        # Delete oldest non-default version if at limit (max 5 versions)
        local versions
        versions=$(aws iam list-policy-versions --policy-arn "$policy_arn" --query "Versions[?IsDefaultVersion==\`false\`].VersionId" --output text)
        local version_count
        version_count=$(echo "$versions" | wc -w)
        if [ "$version_count" -ge 4 ]; then
            local oldest
            oldest=$(echo "$versions" | tr '\t' '\n' | tail -1)
            aws iam delete-policy-version --policy-arn "$policy_arn" --version-id "$oldest" 2>/dev/null || true
        fi
        aws iam create-policy-version \
            --policy-arn "$policy_arn" \
            --policy-document "$policy_doc" \
            --set-as-default \
            --output text > /dev/null
        ok "Policy updated to latest version"
    else
        info "Creating policy: ${policy_name}"
        aws iam create-policy \
            --policy-name "$policy_name" \
            --policy-document "$policy_doc" \
            --description "S3, DynamoDB, Bedrock, ECR, CloudWatch access for Shafanna" \
            --output text > /dev/null
        ok "Policy created: ${policy_name}"
    fi

    # Attach policy to role
    aws iam attach-role-policy \
        --role-name "$SHAFANNA_ROLE" \
        --policy-arn "$policy_arn"
    ok "Policy attached to ${SHAFANNA_ROLE}"
}

attach_etl_policies() {
    step "Attaching policies to ${ETL_ROLE}"

    local policy_name="maroon-etl-github-actions-policy"
    local policy_arn="arn:aws:iam::${AWS_ACCOUNT_ID}:policy/${policy_name}"

    local policy_doc
    policy_doc=$(cat <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "S3DataLakeAccess",
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:GetObject",
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::${MAIN_BUCKET}",
                "arn:aws:s3:::${MAIN_BUCKET}/*",
                "arn:aws:s3:::${RESTRICTED_BUCKET}",
                "arn:aws:s3:::${RESTRICTED_BUCKET}/*"
            ]
        },
        {
            "Sid": "DynamoDBAgentMemory",
            "Effect": "Allow",
            "Action": [
                "dynamodb:GetItem",
                "dynamodb:PutItem",
                "dynamodb:Query",
                "dynamodb:UpdateItem"
            ],
            "Resource": "arn:aws:dynamodb:${AWS_REGION}:${AWS_ACCOUNT_ID}:table/${DYNAMO_TABLE}"
        },
        {
            "Sid": "BedrockDeepSeek",
            "Effect": "Allow",
            "Action": "bedrock:InvokeModel",
            "Resource": "arn:aws:bedrock:${AWS_REGION}::foundation-model/deepseek.*"
        },
        {
            "Sid": "ECRAccess",
            "Effect": "Allow",
            "Action": [
                "ecr:GetAuthorizationToken",
                "ecr:BatchCheckLayerAvailability",
                "ecr:GetDownloadUrlForLayer",
                "ecr:BatchGetImage",
                "ecr:PutImage",
                "ecr:InitiateLayerUpload",
                "ecr:UploadLayerPart",
                "ecr:CompleteLayerUpload"
            ],
            "Resource": "arn:aws:ecr:${AWS_REGION}:${AWS_ACCOUNT_ID}:repository/${ECR_REPO}"
        },
        {
            "Sid": "ECRAuth",
            "Effect": "Allow",
            "Action": "ecr:GetAuthorizationToken",
            "Resource": "*"
        },
        {
            "Sid": "CloudWatchLogs",
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents",
                "logs:DescribeLogGroups",
                "logs:DescribeLogStreams"
            ],
            "Resource": "arn:aws:logs:${AWS_REGION}:${AWS_ACCOUNT_ID}:log-group:/maroon/*"
        }
    ]
}
EOF
)

    # Create or update the policy
    if aws iam get-policy --policy-arn "$policy_arn" > /dev/null 2>&1; then
        ok "Policy exists: ${policy_name}"
        info "Creating new policy version..."
        local versions
        versions=$(aws iam list-policy-versions --policy-arn "$policy_arn" --query "Versions[?IsDefaultVersion==\`false\`].VersionId" --output text)
        local version_count
        version_count=$(echo "$versions" | wc -w)
        if [ "$version_count" -ge 4 ]; then
            local oldest
            oldest=$(echo "$versions" | tr '\t' '\n' | tail -1)
            aws iam delete-policy-version --policy-arn "$policy_arn" --version-id "$oldest" 2>/dev/null || true
        fi
        aws iam create-policy-version \
            --policy-arn "$policy_arn" \
            --policy-document "$policy_doc" \
            --set-as-default \
            --output text > /dev/null
        ok "Policy updated to latest version"
    else
        info "Creating policy: ${policy_name}"
        aws iam create-policy \
            --policy-name "$policy_name" \
            --policy-document "$policy_doc" \
            --description "S3, DynamoDB, Bedrock, ECR, CloudWatch access for MAROON-ETL" \
            --output text > /dev/null
        ok "Policy created: ${policy_name}"
    fi

    # Attach policy to role
    aws iam attach-role-policy \
        --role-name "$ETL_ROLE" \
        --policy-arn "$policy_arn"
    ok "Policy attached to ${ETL_ROLE}"
}

# -----------------------------------------------------------------------------
# Step 6: ECR Repository
# -----------------------------------------------------------------------------
create_ecr_repo() {
    step "Creating ECR Repository: ${ECR_REPO}"

    if aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$AWS_REGION" > /dev/null 2>&1; then
        ok "ECR repository already exists: ${ECR_REPO}"
    else
        info "Creating ECR repository: ${ECR_REPO}"
        aws ecr create-repository \
            --repository-name "$ECR_REPO" \
            --region "$AWS_REGION" \
            --image-scanning-configuration scanOnPush=true \
            --encryption-configuration encryptionType=AES256 \
            --output text > /dev/null
        ok "ECR repository created: ${ECR_REPO}"
    fi

    # Set lifecycle policy to keep only last 10 images (cost control)
    info "Setting image lifecycle policy (keep last 10 images)"
    aws ecr put-lifecycle-policy \
        --repository-name "$ECR_REPO" \
        --region "$AWS_REGION" \
        --lifecycle-policy-text '{
            "rules": [{
                "rulePriority": 1,
                "description": "Keep only last 10 images",
                "selection": {
                    "tagStatus": "any",
                    "countType": "imageCountMoreThan",
                    "countNumber": 10
                },
                "action": {
                    "type": "expire"
                }
            }]
        }' \
        --output text > /dev/null
    ok "Lifecycle policy set (max 10 images)"
}

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
print_summary() {
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                BOOTSTRAP COMPLETE                                ║${NC}"
    echo -e "${GREEN}╠══════════════════════════════════════════════════════════════════╣${NC}"
    echo -e "${GREEN}║                                                                  ║${NC}"
    echo -e "${GREEN}║  S3 Buckets:                                                     ║${NC}"
    echo -e "${GREEN}║    - ${MAIN_BUCKET}               ║${NC}"
    echo -e "${GREEN}║    - ${RESTRICTED_BUCKET}      ║${NC}"
    echo -e "${GREEN}║    - ${SHAFANNA_BUCKET}                     ║${NC}"
    echo -e "${GREEN}║                                                                  ║${NC}"
    echo -e "${GREEN}║  DynamoDB:                                                       ║${NC}"
    echo -e "${GREEN}║    - ${DYNAMO_TABLE} (pk/sk, PAY_PER_REQUEST, TTL)    ║${NC}"
    echo -e "${GREEN}║                                                                  ║${NC}"
    echo -e "${GREEN}║  OIDC Provider:                                                  ║${NC}"
    echo -e "${GREEN}║    - token.actions.githubusercontent.com                         ║${NC}"
    echo -e "${GREEN}║                                                                  ║${NC}"
    echo -e "${GREEN}║  IAM Roles:                                                      ║${NC}"
    echo -e "${GREEN}║    - ${SHAFANNA_ROLE}                               ║${NC}"
    echo -e "${GREEN}║    - ${ETL_ROLE}                            ║${NC}"
    echo -e "${GREEN}║                                                                  ║${NC}"
    echo -e "${GREEN}║  ECR Repository:                                                 ║${NC}"
    echo -e "${GREEN}║    - ${ECR_REPO}                                            ║${NC}"
    echo -e "${GREEN}║                                                                  ║${NC}"
    echo -e "${GREEN}║  Region: ${AWS_REGION}  |  Account: ${AWS_ACCOUNT_ID}              ║${NC}"
    echo -e "${GREEN}║                                                                  ║${NC}"
    echo -e "${GREEN}║  Next steps:                                                     ║${NC}"
    echo -e "${GREEN}║    1. Add GitHub secrets (role ARNs) to repos                    ║${NC}"
    echo -e "${GREEN}║    2. Push to trigger CI/CD with OIDC auth                       ║${NC}"
    echo -e "${GREEN}║    3. Verify with: aws s3 ls s3://${MAIN_BUCKET}/  ║${NC}"
    echo -e "${GREEN}║                                                                  ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "Role ARNs for GitHub Actions secrets:"
    echo "  AWS_ROLE_ARN (Shafanna):  arn:aws:iam::${AWS_ACCOUNT_ID}:role/${SHAFANNA_ROLE}"
    echo "  AWS_ROLE_ARN (ETL):       arn:aws:iam::${AWS_ACCOUNT_ID}:role/${ETL_ROLE}"
    echo ""
}

# -----------------------------------------------------------------------------
# Main execution
# -----------------------------------------------------------------------------
main() {
    echo ""
    echo -e "${BLUE}╔══════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║     MAROON + SHAFANNA AWS BOOTSTRAP                             ║${NC}"
    echo -e "${BLUE}║     Provisioning infrastructure in us-west-2                     ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════════════════════════════╝${NC}"
    echo ""

    verify_environment
    create_s3_buckets
    create_dynamodb_table
    create_oidc_provider
    create_shafanna_role
    create_etl_role
    attach_shafanna_policies
    attach_etl_policies
    create_ecr_repo
    print_summary
}

main "$@"
