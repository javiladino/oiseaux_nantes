# Guía de Infraestructura — Pipeline de Aves de Nantes

## Alarma de CloudWatch (T038 / FR-016)

Crear una alarma sobre la función Lambda `birds-inaturalist-ingestion` para detectar errores o timeouts.

### AWS CLI

```bash
# Crear el topic SNS para las alertas del pipeline
aws sns create-topic --name birds-pipeline-alerts --region eu-west-3

# Suscribir el correo del responsable del pipeline
aws sns subscribe \
  --topic-arn arn:aws:sns:eu-west-3:<account-id>:birds-pipeline-alerts \
  --protocol email \
  --notification-endpoint <owner-email>

# Alarma: errores de Lambda ≥ 1 en 5 minutos
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

# Alarma: timeout de Lambda (duración cercana al límite de 3 min)
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

## Regla Cron Diaria de EventBridge (T039)

La Lambda se dispara a diario mediante una regla de Amazon EventBridge. El cron está programado
para ejecutarse antes de la actualización programada de Power BI (que se ejecuta a las 08:00
UTC) — Lambda se ejecuta a diario a las **05:00 UTC**.

### Expresión Cron

```
cron(0 5 * * ? *)
```

Equivale a: todos los días a las 05:00 UTC (06:00 hora de París en invierno, 07:00 CEST en verano).

### AWS CLI

```bash
# Crear la regla de EventBridge
aws events put-rule \
  --name "birds-ingestion-daily" \
  --schedule-expression "cron(0 5 * * ? *)" \
  --state ENABLED \
  --description "Daily trigger for birds-inaturalist-ingestion Lambda" \
  --region eu-west-3

# Añadir la Lambda como destino
aws events put-targets \
  --rule birds-ingestion-daily \
  --targets "Id=birds-lambda-target,Arn=arn:aws:lambda:eu-west-3:<account-id>:function:birds-inaturalist-ingestion" \
  --region eu-west-3

# Dar permiso a EventBridge para invocar la Lambda
aws lambda add-permission \
  --function-name birds-inaturalist-ingestion \
  --statement-id "AllowEventBridgeTrigger" \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:eu-west-3:<account-id>:rule/birds-ingestion-daily \
  --region eu-west-3
```

### Permisos IAM Necesarios para el Rol de Ejecución de Lambda

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

Sin ARNs de recurso comodín (constitución IV).
