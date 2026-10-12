# Rol de la EC2 de Airflow.
# Contrato: specs/002-airflow-orchestration/contracts/iam-policy.md
# Sin permisos sobre SSM Parameter Store (el watermark es de la Lambda) ni escritura en raw/.

data "aws_caller_identity" "current" {}

locals {
  account_id       = data.aws_caller_identity.current.account_id
  bucket_arn       = "arn:aws:s3:::${var.bucket_name}"
  alerts_topic_arn = "arn:aws:sns:${var.region}:${local.account_id}:${var.alerts_topic_name}"
  glue_prefix      = "arn:aws:glue:${var.region}:${local.account_id}"
}

data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "airflow" {
  name               = "birds-airflow-ec2-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
}

data "aws_iam_policy_document" "orchestration" {
  statement {
    sid       = "InvokeIngestionLambda"
    actions   = ["lambda:InvokeFunction"]
    resources = ["arn:aws:lambda:${var.region}:${local.account_id}:function:${var.lambda_function_name}"]
  }

  statement {
    sid = "AthenaPrimaryWorkgroup"
    actions = [
      "athena:StartQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:StopQueryExecution",
      "athena:GetWorkGroup",
    ]
    resources = ["arn:aws:athena:${var.region}:${local.account_id}:workgroup/primary"]
  }

  statement {
    sid = "GlueCatalogBirds"
    actions = [
      "glue:GetDatabase",
      "glue:GetDatabases",
      "glue:CreateDatabase",
      "glue:GetTable",
      "glue:GetTables",
      "glue:CreateTable",
      "glue:UpdateTable",
      "glue:DeleteTable",
      "glue:GetPartition",
      "glue:GetPartitions",
      "glue:GetTableVersions",
      "glue:DeleteTableVersion",
      "glue:BatchCreatePartition",
      "glue:BatchDeletePartition",
    ]
    resources = [
      "${local.glue_prefix}:catalog",
      "${local.glue_prefix}:database/birds_raw",
      "${local.glue_prefix}:database/birds_dbt",
      "${local.glue_prefix}:table/birds_raw/*",
      "${local.glue_prefix}:table/birds_dbt/*",
    ]
  }

  statement {
    sid       = "S3ListBucket"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [local.bucket_arn]
  }

  statement {
    sid       = "S3ReadRaw"
    actions   = ["s3:GetObject"]
    resources = ["${local.bucket_arn}/raw/inaturalist/observations/*"]
  }

  statement {
    sid     = "S3ReadWriteProcessedAndResults"
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"]
    resources = [
      "${local.bucket_arn}/processed/*",
      "${local.bucket_arn}/athena-results/*",
    ]
  }

  statement {
    sid       = "PublishAlerts"
    actions   = ["sns:Publish"]
    resources = [local.alerts_topic_arn]
  }
}

resource "aws_iam_role_policy" "orchestration" {
  name   = "birds-airflow-orchestration"
  role   = aws_iam_role.airflow.id
  policy = data.aws_iam_policy_document.orchestration.json
}

# Excepción justificada (constitución IV, plan.md Complexity Tracking): el agente de Session
# Manager necesita acciones que AWS no permite restringir por recurso.
resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.airflow.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "airflow" {
  name = "birds-airflow-ec2-profile"
  role = aws_iam_role.airflow.name
}
