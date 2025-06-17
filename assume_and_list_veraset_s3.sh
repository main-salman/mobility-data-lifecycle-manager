#!/bin/bash
# Script to assume Veraset S3 access role, list contents of a specific S3 folder, and attempt to sync .parquet files from a subfolder

ROLE_ARN="arn:aws:iam::651706782157:role/VerasetS3AccessRole"
SESSION_NAME="veraset-debug"
S3_PATH="s3://veraset-prd-platform-us-west-2/output/United_Nations/731d7367-37d2-4fea-8d22-2e912fba5e70/"
S3_SUBFOLDER="s3://veraset-prd-platform-us-west-2/output/United_Nations/731d7367-37d2-4fea-8d22-2e912fba5e70/date=2025-06-10/"
LOCAL_DIR="./veraset-download-test/"

# Assume the role
ASSUME_OUTPUT=$(aws sts assume-role --role-arn "$ROLE_ARN" --role-session-name "$SESSION_NAME" --output json)

if [ $? -ne 0 ]; then
  echo "Failed to assume role. Check your AWS credentials and permissions."
  exit 1
fi

# Extract credentials using jq
export AWS_ACCESS_KEY_ID=$(echo "$ASSUME_OUTPUT" | jq -r .Credentials.AccessKeyId)
export AWS_SECRET_ACCESS_KEY=$(echo "$ASSUME_OUTPUT" | jq -r .Credentials.SecretAccessKey)
export AWS_SESSION_TOKEN=$(echo "$ASSUME_OUTPUT" | jq -r .Credentials.SessionToken)

if [ -z "$AWS_ACCESS_KEY_ID" ] || [ -z "$AWS_SECRET_ACCESS_KEY" ] || [ -z "$AWS_SESSION_TOKEN" ]; then
  echo "Failed to extract temporary credentials."
  exit 1
fi

echo "Temporary credentials set. Listing contents of $S3_PATH ..."
aws s3 ls "$S3_PATH"

# Attempt to sync .parquet files from the subfolder
mkdir -p "$LOCAL_DIR"
echo "Attempting to sync .parquet files from $S3_SUBFOLDER to $LOCAL_DIR ..."
aws s3 sync "$S3_SUBFOLDER" "$LOCAL_DIR" --exclude "*" --include "*.parquet"

exit $? 