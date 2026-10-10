# Infrastructure Guide — Nantes Birds Pipeline

## CloudWatch Alarm (T038 / FR-016)

Create an alarm on the Lambda `birds-inaturalist-ingestion` function to detect errors or timeouts.

### AWS CLI

```bash
# Create SNS topic for pipeline alerts
aws sns create-topic --name birds-pipeline-alerts --region eu-west-3

# Subscribe pipeline owner email
aws sns subscribe \
  --topic-arn arn:aws:sns:eu-west-3:<account-id>:birds-pipeline-alerts \
  --protocol email \
  --notification-endpoint <owner-email>

# Alarm: Lambda errors ≥ 1 over 5 minutes
aws cloudwatch put-metric-alarm \
  --alarm-name "birds-ingestion-errors" \
  --alarm-description "Lambda error or timeout detected" \
  --metric-name Errors \
  --namespace AWS/Lambda \
  --dimensions Name=FunctionName,Value=birds-inaturalist-ingestion \
  --statistic Sum \
  --period 300 \
  --evaluation-periods 1 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --alarm-actions arn:aws:sns:eu-west-3:<account-id>:birds-pipeline-alerts \
  --region eu-west-3

# Alarm: Lambda timeout (Duration approaching 3-min cap)
aws cloudwatch put-metric-alarm \
  --alarm-name "birds-ingestion-duration" \
  --alarm-description "Lambda execution approaching 3-minute timeout" \
  --metric-name Duration \
  --namespace AWS/Lambda \
  --dimensions Name=FunctionName,Value=birds-inaturalist-ingestion \
  --statistic Maximum \
  --period 300 \
  --evaluation-periods 1 \
  --threshold 150000 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --alarm-actions arn:aws:sns:eu-west-3:<account-id>:birds-pipeline-alerts \
  --region eu-west-3
```

---

## EventBridge Daily Cron Rule (T039)

The Lambda is triggered daily via an Amazon EventBridge rule. The cron is set to run before the
Power BI scheduled refresh (which runs at 08:00 UTC) — Lambda runs at **05:00 UTC** daily.

### Cron Expression

```
cron(0 5 * * ? *)
```

Translates to: every day at 05:00 UTC (07:00 Paris time in winter, 07:00 CEST in summer).

### AWS CLI

```bash
# Create EventBridge rule
aws events put-rule \
  --name "birds-ingestion-daily" \
  --schedule-expression "cron(0 5 * * ? *)" \
  --state ENABLED \
  --description "Daily trigger for birds-inaturalist-ingestion Lambda" \
  --region eu-west-3

# Add Lambda as target
aws events put-targets \
  --rule birds-ingestion-daily \
  --targets "Id=birds-lambda-target,Arn=arn:aws:lambda:eu-west-3:<account-id>:function:birds-inaturalist-ingestion" \
  --region eu-west-3

# Grant EventBridge permission to invoke Lambda
aws lambda add-permission \
  --function-name birds-inaturalist-ingestion \
  --statement-id "AllowEventBridgeTrigger" \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:eu-west-3:<account-id>:rule/birds-ingestion-daily \
  --region eu-west-3
```

### Required IAM Permissions for Lambda Execution Role

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3WriteRawObservations",
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::<bucket>/raw/inaturalist/observations/*"
    },
    {
      "Sid": "SSMWatermark",
      "Effect": "Allow",
      "Action": ["ssm:GetParameter", "ssm:PutParameter"],
      "Resource": "arn:aws:ssm:eu-west-3:<account-id>:parameter/birds-pipeline/last_successful_run_date"
    },
    {
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:eu-west-3:<account-id>:log-group:/aws/lambda/birds-inaturalist-ingestion:*"
    }
  ]
}
```

No wildcard resource ARNs (constitution IV).
