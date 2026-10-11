# Contrato: Permisos IAM del Rol `birds-airflow-ec2-role`

**Consumidor**: instancia EC2 de Airflow (vía instance profile)
**Definido en**: `infra/airflow/iam.tf`
**Fecha**: 2026-10-11

Cada sentencia lista sus recursos con ARN concreto (constitución IV, FR-014). La única excepción
es la política gestionada de Session Manager, justificada en el Complexity Tracking del plan.

Marcadores: `<account-id>`, `<bucket>`, `<region>` = `eu-west-3`.

---

## Política en línea `birds-airflow-orchestration`

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeIngestionLambda",
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "arn:aws:lambda:eu-west-3:<account-id>:function:birds-inaturalist-ingestion"
    },
    {
      "Sid": "AthenaPrimaryWorkgroup",
      "Effect": "Allow",
      "Action": [
        "athena:StartQueryExecution",
        "athena:GetQueryExecution",
        "athena:GetQueryResults",
        "athena:StopQueryExecution",
        "athena:GetWorkGroup"
      ],
      "Resource": "arn:aws:athena:eu-west-3:<account-id>:workgroup/primary"
    },
    {
      "Sid": "GlueCatalogBirds",
      "Effect": "Allow",
      "Action": [
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
        "glue:BatchCreatePartition",
        "glue:BatchDeletePartition"
      ],
      "Resource": [
        "arn:aws:glue:eu-west-3:<account-id>:catalog",
        "arn:aws:glue:eu-west-3:<account-id>:database/birds_raw",
        "arn:aws:glue:eu-west-3:<account-id>:database/birds_dbt",
        "arn:aws:glue:eu-west-3:<account-id>:table/birds_raw/*",
        "arn:aws:glue:eu-west-3:<account-id>:table/birds_dbt/*"
      ]
    },
    {
      "Sid": "S3ListBucket",
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::<bucket>"
    },
    {
      "Sid": "S3ReadRaw",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::<bucket>/raw/inaturalist/observations/*"
    },
    {
      "Sid": "S3ReadWriteProcessedAndResults",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"],
      "Resource": [
        "arn:aws:s3:::<bucket>/processed/*",
        "arn:aws:s3:::<bucket>/athena-results/*"
      ]
    },
    {
      "Sid": "PublishAlerts",
      "Effect": "Allow",
      "Action": "sns:Publish",
      "Resource": "arn:aws:sns:eu-west-3:<account-id>:birds-pipeline-alerts"
    }
  ]
}
```

Notas:
- `table/birds_dbt/*` usa un comodín **dentro** de una base de datos concreta: identifica las
  tablas que gestiona dbt, cuyo nombre no se conoce de antemano. No es un ARN comodín de recurso
  completo.
- `s3:ListBucket` puede restringirse más con una condición `s3:prefix` en
  `raw/`, `processed/` y `athena-results/`; se valida en la implementación con `dbt run`.
- **Sin** permisos sobre SSM Parameter Store: el orquestador nunca toca el watermark (FR-002, FR-009).
- **Sin** `s3:PutObject` sobre `raw/`: solo la Lambda escribe en la zona raw (constitución I).

## Política gestionada adjunta

| Política | Motivo |
|----------|--------|
| `arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore` | Agente de Session Manager para acceder sin puertos abiertos (FR-015). Excepción justificada. |

## Security group `birds-airflow-sg`

| Dirección | Reglas |
|-----------|--------|
| Entrada | **Ninguna** |
| Salida | HTTPS 443 a `0.0.0.0/0` (APIs de AWS, GitHub, PyPI) |

## Evolución del contrato

La lista de acciones de Glue y S3 que necesita dbt-athena se validará con la primera ejecución
real (T021). Si aparece un `AccessDenied`, se añade aquí la acción mínima concreta, sobre un ARN
concreto, en el mismo PR que la cambia en `infra/airflow/iam.tf`.

## Verificación

El escenario 5 de [quickstart.md](../quickstart.md) comprueba con el IAM Policy Simulator que
el rol puede invocar la Lambda y **no** puede escribir en `raw/` ni leer el parámetro SSM.
