# Instructivo de Despliegue en AWS — Pipeline de Aves de Nantes

Guía paso a paso para desplegar desde cero, en una cuenta de AWS sin recursos previos del
proyecto, el pipeline completo: ingesta (feature 001) y orquestación con Airflow (feature 002).

| | |
|---|---|
| **Región** | `eu-west-3` (París) |
| **Tiempo estimado** | 1,5–2 horas (la mayor parte es esperar instalaciones) |
| **Coste mensual aproximado** | ~20 USD: EC2 de Airflow ~19 USD; Lambda, S3, Athena y SNS, céntimos |
| **Tareas que cubre** | T016, T021 y T022 de `specs/002-airflow-orchestration/tasks.md`, y los escenarios 1 y 3–5 de la 001 |

> **Antes de empezar**: los pasos 2 a 10 crean recursos reales que generan coste. El paso 11
> explica cómo detenerlos o eliminarlos.

---

## Índice

0. [Requisitos previos](#paso-0--requisitos-previos)
1. [Fusionar el PR de Airflow en `main`](#paso-1--fusionar-el-pr-de-airflow-en-main)
2. [Bucket S3, bases de datos de Glue y alertas](#paso-2--bucket-s3-bases-de-datos-de-glue-y-alertas)
3. [Función Lambda de ingesta](#paso-3--función-lambda-de-ingesta)
4. [Carga histórica inicial (desde tu máquina)](#paso-4--carga-histórica-inicial-desde-tu-máquina)
5. [Tabla raw en Athena](#paso-5--tabla-raw-en-athena)
6. [Desplegar la EC2 de Airflow con Terraform](#paso-6--desplegar-la-ec2-de-airflow-con-terraform)
7. [Verificar la instalación](#paso-7--verificar-la-instalación)
8. [Primera ejecución del DAG (validación)](#paso-8--primera-ejecución-del-dag-validación)
9. [Pasar a producción](#paso-9--pasar-a-producción)
10. [Comprobaciones de los días siguientes](#paso-10--comprobaciones-de-los-días-siguientes)
11. [Detener o eliminar todo](#paso-11--detener-o-eliminar-todo)
12. [Problemas frecuentes](#problemas-frecuentes)

---

## Paso 0 — Requisitos previos

### Herramientas en tu máquina

| Herramienta | Comprobación | Notas |
|-------------|--------------|-------|
| AWS CLI v2 | `aws --version` | Con un perfil con permisos de administrador sobre la cuenta |
| Session Manager plugin | `session-manager-plugin --version` | `brew install --cask session-manager-plugin` |
| Terraform ≥ 1.6 | `terraform version` | |
| Python 3.11+ | `python3 --version` | Para empaquetar la Lambda y la carga inicial |
| GitHub CLI | `gh auth status` | Solo para fusionar el PR |
| Espacio en disco | `df -h .` | **Al menos 1,5 GB libres**: el provider de AWS de Terraform ocupa ~700 MB |

### Variables de trabajo

Todos los comandos de esta guía usan estas variables. Ejecútalas en la terminal donde vayas a
trabajar (y otra vez si abres una nueva):

```bash
export AWS_REGION=eu-west-3
export AWS_DEFAULT_REGION=eu-west-3
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export BUCKET=oiseaux-nantes-$ACCOUNT_ID          # el nombre de bucket debe ser único en todo S3
export ALERT_EMAIL=<tu-email>                     # recibirá las alertas del pipeline
export TOPIC_ARN=arn:aws:sns:$AWS_REGION:$ACCOUNT_ID:birds-pipeline-alerts
export REPO=$(git rev-parse --show-toplevel)       # ejecutar desde dentro del repositorio

echo "Cuenta: $ACCOUNT_ID  Bucket: $BUCKET"
```

### Recomendado: alerta de presupuesto

Para no llevarte sorpresas, crea en la consola **Billing → Budgets** un presupuesto mensual de
25 USD con aviso por email al 80 %.

---

## Paso 1 — Fusionar el PR de Airflow en `main`

La EC2 clona la rama `main` del repositorio al arrancar, así que el código de Airflow debe estar
fusionado antes del paso 6.

```bash
gh pr checks 1          # la CI "Airflow CI" debe estar en verde
gh pr merge 1 --merge --delete-branch
git checkout main && git pull
```

> La constitución pide la aprobación de un revisor para la enmienda 1.1.0. GitHub no permite
> aprobar tu propio PR: en un proyecto individual, revísalo y fusiónalo tú.

---

## Paso 2 — Bucket S3, bases de datos de Glue y alertas

```bash
# 2.1 Bucket del data lake (privado y cifrado por defecto)
aws s3api create-bucket --bucket "$BUCKET" \
  --create-bucket-configuration LocationConstraint=$AWS_REGION
aws s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# 2.2 Bases de datos del catálogo de Glue
aws glue create-database --database-input '{"Name":"birds_raw"}'
aws glue create-database --database-input '{"Name":"birds_dbt"}'

# 2.3 Topic SNS de alertas y suscripción por email
aws sns create-topic --name birds-pipeline-alerts
aws sns subscribe --topic-arn "$TOPIC_ARN" --protocol email --notification-endpoint "$ALERT_EMAIL"
```

**Acción manual:** abre el email "AWS Notification - Subscription Confirmation" y pulsa
**Confirm subscription**. Sin esto no llega ninguna alerta.

```bash
aws sns list-subscriptions-by-topic --topic-arn "$TOPIC_ARN" \
  --query 'Subscriptions[0].SubscriptionArn'
# Esperado: un ARN (no "PendingConfirmation")
```

---

## Paso 3 — Función Lambda de ingesta

### 3.1 Rol de ejecución (permisos de `docs/infrastructure.md`)

```bash
aws iam create-role --role-name birds-ingestion-lambda-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]
  }'

aws iam put-role-policy --role-name birds-ingestion-lambda-role \
  --policy-name birds-ingestion \
  --policy-document "{
    \"Version\": \"2012-10-17\",
    \"Statement\": [
      {\"Sid\": \"S3WriteRawObservations\", \"Effect\": \"Allow\", \"Action\": \"s3:PutObject\",
       \"Resource\": \"arn:aws:s3:::$BUCKET/raw/inaturalist/observations/*\"},
      {\"Sid\": \"SSMWatermark\", \"Effect\": \"Allow\", \"Action\": [\"ssm:GetParameter\", \"ssm:PutParameter\"],
       \"Resource\": \"arn:aws:ssm:$AWS_REGION:$ACCOUNT_ID:parameter/birds-pipeline/last_successful_run_date\"},
      {\"Sid\": \"CloudWatchLogs\", \"Effect\": \"Allow\", \"Action\": [\"logs:CreateLogGroup\", \"logs:CreateLogStream\", \"logs:PutLogEvents\"],
       \"Resource\": \"arn:aws:logs:$AWS_REGION:$ACCOUNT_ID:log-group:/aws/lambda/birds-inaturalist-ingestion:*\"}
    ]
  }"
```

### 3.2 Empaquetar y crear la función

`requests` no viene en el runtime de Lambda, así que se incluye en el zip:

```bash
BUILD=$(mktemp -d)
pip install requests -t "$BUILD" --quiet
cp "$REPO"/ingestion/*.py "$BUILD"/
(cd "$BUILD" && zip -qr ../lambda.zip .) && mv "$BUILD/../lambda.zip" "$REPO/lambda.zip"

sleep 10   # el rol IAM tarda unos segundos en propagarse

aws lambda create-function --function-name birds-inaturalist-ingestion \
  --runtime python3.12 --handler handler.lambda_handler \
  --role arn:aws:iam::$ACCOUNT_ID:role/birds-ingestion-lambda-role \
  --zip-file fileb://$REPO/lambda.zip \
  --timeout 180 --memory-size 512 \
  --environment "Variables={BIRDS_S3_BUCKET=$BUCKET}"

rm -rf "$BUILD" "$REPO/lambda.zip"
```

### 3.3 Alarmas de CloudWatch

```bash
aws cloudwatch put-metric-alarm --alarm-name birds-ingestion-errors \
  --metric-name Errors --namespace AWS/Lambda \
  --dimensions Name=FunctionName,Value=birds-inaturalist-ingestion \
  --statistic Sum --period 300 --evaluation-periods 1 --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold --alarm-actions "$TOPIC_ARN"

aws cloudwatch put-metric-alarm --alarm-name birds-ingestion-duration \
  --metric-name Duration --namespace AWS/Lambda \
  --dimensions Name=FunctionName,Value=birds-inaturalist-ingestion \
  --statistic Maximum --period 300 --evaluation-periods 1 --threshold 150000 \
  --comparison-operator GreaterThanOrEqualToThreshold --alarm-actions "$TOPIC_ARN"
```

> **No invoques todavía la Lambda.** Sin watermark, su primera ejecución intentaría descargar
> todo el histórico y superaría el límite de 3 minutos (ver paso 4).

### 3.4 (Opcional) Regla de EventBridge desactivada

Airflow será el único programador. Si quieres tener disponible la vía de reversión descrita en
`docs/airflow-operations.md`, crea la regla **ya desactivada**:

```bash
aws events put-rule --name birds-ingestion-daily \
  --schedule-expression "cron(0 5 * * ? *)" --state DISABLED
aws events put-targets --rule birds-ingestion-daily \
  --targets "Id"="1","Arn"="arn:aws:lambda:$AWS_REGION:$ACCOUNT_ID:function:birds-inaturalist-ingestion"
aws lambda add-permission --function-name birds-inaturalist-ingestion \
  --statement-id eventbridge-daily --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:$AWS_REGION:$ACCOUNT_ID:rule/birds-ingestion-daily
```

---

## Paso 4 — Carga histórica inicial (desde tu máquina)

**Por qué este paso existe:** el bbox de Nantes tiene unas **18.500 observaciones de aves** en
iNaturalist (consulta del 2026-10-11). Son ~93 páginas a ~1 petición/s, entre 3 y 5 minutos,
y la Lambda tiene un límite de 3 minutos (constitución IV). Si la primera ejecución fuera en
Lambda, terminaría por timeout, nunca guardaría el watermark y fallaría todos los días.

La solución es ejecutar **una sola vez** el mismo código de ingesta desde tu máquina, sin límite
de tiempo, con tus credenciales. Escribe el histórico en S3 y guarda el watermark; a partir de
ahí la Lambda solo descarga lo nuevo de cada día.

```bash
python3 -m venv /tmp/ingest-venv
/tmp/ingest-venv/bin/pip install --quiet -r "$REPO/ingestion/requirements.txt"

cd "$REPO/ingestion"
BIRDS_S3_BUCKET=$BUCKET /tmp/ingest-venv/bin/python -c \
  "from handler import lambda_handler; print(lambda_handler({}, None))"
cd "$REPO"
# Esperado (tras 3–5 min): {'statusCode': 200, 'body': 'Ingested ~18500 observations'}
```

Comprobaciones:

```bash
aws s3 ls "s3://$BUCKET/raw/inaturalist/observations/" --recursive --human-readable
# Esperado: un archivo year=AAAA/month=MM/AAAAMMDDTHHMMSS.json

aws ssm get-parameter --name /birds-pipeline/last_successful_run_date --query Parameter.Value
# Esperado: la fecha y hora de la carga (UTC)
```

Ahora sí, prueba la Lambda (ejecución incremental, debe tardar segundos):

```bash
aws lambda invoke --function-name birds-inaturalist-ingestion /tmp/lambda-out.json \
  --query FunctionError && cat /tmp/lambda-out.json
# Esperado: FunctionError vacío (null) y {"statusCode": 200, "body": "Ingested N observations"} con N pequeño
```

---

## Paso 5 — Tabla raw en Athena

> **Aviso — cambio respecto a la documentación de la 001.** El README y el quickstart de la 001
> indican registrar la tabla raw con `dbt run-operation stage_external_sources`. Eso **no
> funciona con Athena**: el paquete `dbt-labs/dbt_external_tables` no tiene implementación para
> este adaptador y falla con *"Staging external sources is not implemented for the default
> adapter"*. Además, como la ingesta crea una partición nueva cada mes, alguien tendría que
> registrarla cada mes, y el DAG no lo hace.
>
> Esta guía crea la tabla con **partition projection**: Athena deduce las particiones
> `year=/month=` por sí mismo, sin `MSCK REPAIR` ni registro mensual. Conviene versionar este
> DDL en el repositorio (cambio pendiente; ver la sección final).

1. Abre la consola de **Athena** en `eu-west-3` → **Query editor**.
2. Si es la primera vez, en **Settings** fija la ubicación de resultados:
   `s3://<tu-bucket>/athena-results/`.
3. Ejecuta este DDL **sustituyendo `<tu-bucket>` en las dos líneas marcadas**:

```sql
CREATE EXTERNAL TABLE IF NOT EXISTS birds_raw.observations (
  id                  bigint,
  created_at          string,
  observed_on         string,
  location            string,
  positional_accuracy int,
  quality_grade       string,
  taxon  struct<id:bigint, name:string, preferred_common_name:string, rank:string, threatened:boolean>,
  `user` struct<id:bigint, login:string, name:string>
)
PARTITIONED BY (year string, month string)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
WITH SERDEPROPERTIES ('ignore.malformed.json' = 'true')
LOCATION 's3://<tu-bucket>/raw/inaturalist/observations/'                          -- ← sustituir
TBLPROPERTIES (
  'projection.enabled'         = 'true',
  'projection.year.type'       = 'integer',
  'projection.year.range'      = '2024,2040',
  'projection.month.type'      = 'integer',
  'projection.month.range'     = '1,12',
  'projection.month.digits'    = '2',
  'storage.location.template'  = 's3://<tu-bucket>/raw/inaturalist/observations/year=${year}/month=${month}/'  -- ← sustituir
);
```

4. Comprueba que lee los datos de la carga inicial:

```sql
SELECT year, month, COUNT(*) AS observaciones, COUNT(DISTINCT id) AS distintas
FROM birds_raw.observations
GROUP BY year, month;
-- Esperado: una fila con ~18.500 observaciones
```

---

## Paso 6 — Desplegar la EC2 de Airflow con Terraform

```bash
cd "$REPO/infra/airflow"
terraform init
terraform plan -var "bucket_name=$BUCKET" -out tfplan
```

Revisa el plan: debe crear **6 recursos** (rol IAM, política en línea, adjunto de
`AmazonSSMManagedInstanceCore`, instance profile, security group e instancia EC2) y no modificar
ni destruir nada. Después:

```bash
terraform apply tfplan
terraform output
cd "$REPO"
export INSTANCE_ID=$(terraform -chdir=infra/airflow output -raw instance_id)
```

> El estado de Terraform se guarda en `infra/airflow/terraform.tfstate` (ignorado por git).
> **No lo borres**: sin él, Terraform no puede actualizar ni destruir la infraestructura.

La instancia se instala sola (swap, PostgreSQL, Airflow, dbt, servicios). Tarda **10–20
minutos**. Para seguir el progreso (espera 2–3 minutos a que el agente de Session Manager se
registre):

```bash
aws ssm start-session --target "$INSTANCE_ID"
# Dentro de la sesión:
sudo tail -f /var/log/airflow-bootstrap.log
# Termina con "== Bootstrap de Airflow completado ==". Ctrl+C y `exit` para salir.
```

---

## Paso 7 — Verificar la instalación

Escenario 1 del quickstart de la 002:

```bash
# Desde tu máquina: el security group no tiene reglas de entrada
aws ec2 describe-security-groups --group-names birds-airflow-sg \
  --query 'SecurityGroups[0].IpPermissions'
# Esperado: []

# En la instancia (aws ssm start-session --target "$INSTANCE_ID"):
sudo systemctl is-active postgresql airflow-api-server airflow-scheduler airflow-dag-processor
# Esperado: active ×4

sudo -u airflow bash -c 'set -a; source /etc/airflow/airflow.env; set +a; /opt/airflow-venv/bin/airflow dags list'
# Esperado: nantes_birds_pipeline, con is_paused = True

sudo -u airflow bash -c 'set -a; source /etc/airflow/airflow.env; set +a; /opt/airflow-venv/bin/airflow dags list-import-errors'
# Esperado: sin errores

sudo cat /opt/airflow/simple_auth_manager_passwords.json.generated
# Guarda la contraseña del usuario admin
```

Abre la UI desde tu máquina (deja la terminal abierta mientras la uses):

```bash
terraform -chdir=infra/airflow output -raw ui_tunnel_command | sh
# Navegador: http://localhost:8080  →  usuario admin + la contraseña anterior
```

Deberías ver el DAG `nantes_birds_pipeline` **pausado**, con la tarea de ingesta y el grupo
`dbt_medallion`.

---

## Paso 8 — Primera ejecución del DAG (validación)

Con el DAG todavía pausado, ejecútalo de principio a fin sin el scheduler (`airflow dags test`
funciona aunque esté pausado). La primera vez construye todos los modelos desde cero.

```bash
# En la instancia:
sudo -u airflow bash -c 'set -a; source /etc/airflow/airflow.env; set +a; \
  /opt/airflow-venv/bin/airflow dags test nantes_birds_pipeline' 2>&1 | tail -40
# Esperado: todas las tareas en success; tarda unos 5–15 minutos
```

Comprueba el resultado en Athena:

```sql
SELECT COUNT(*) AS filas, COUNT(DISTINCT observation_id) AS distintas
FROM birds_dbt.fct_observations;
-- Esperado: ambos números iguales y del orden de la carga inicial (menos lo que filtra el bbox)

SELECT COUNT(*) FROM birds_dbt.dim_species;
SELECT COUNT(*) FROM birds_dbt.dim_users;
SELECT MIN(date_key), MAX(date_key) FROM birds_dbt.dim_date;
```

**Si una tarea falla:** revisa su log en la UI. Si es un `AccessDenied`, falta un permiso en el
rol de Airflow: añade la acción mínima concreta a
`specs/002-airflow-orchestration/contracts/iam-policy.md` y a `infra/airflow/iam.tf`, aplica con
`terraform apply -var "bucket_name=$BUCKET"` y repite el paso. Otros errores, en
[Problemas frecuentes](#problemas-frecuentes).

---

## Paso 9 — Pasar a producción

Solo cuando el paso 8 haya terminado en `success`:

```bash
# 1. EventBridge desactivado (si creaste la regla en el paso 3.4)
aws events describe-rule --name birds-ingestion-daily --query State
# Esperado: "DISABLED"

# 2. Activar el DAG (en la instancia)
sudo -u airflow bash -c 'set -a; source /etc/airflow/airflow.env; set +a; \
  /opt/airflow-venv/bin/airflow dags unpause nantes_birds_pipeline'
```

> **Nunca** tengas activos a la vez la regla de EventBridge y el DAG.

Al activarlo, Airflow puede lanzar en ese momento la ejecución del último intervalo pendiente
(`catchup=False` lanza como mucho una). Es normal y no genera duplicados.

---

## Paso 10 — Comprobaciones de los días siguientes

| Cuándo | Qué comprobar |
|--------|---------------|
| Mañana, después de las 05:30 UTC | En la UI, la ejecución programada en verde; `fct_observations` con datos del día |
| Si llega un email | Seguir `docs/airflow-operations.md` §4 (recuperar una ejecución fallida) |
| Primera semana | Escenarios pendientes del quickstart de la 002: 3 (fallos y alertas), 4 (reconstrucción completa), 5 (IAM), 6 (programador único), 7 (retraso) |
| Al cabo de una semana | Coste en **Cost Explorer** filtrando por la etiqueta `component = airflow` (≤ 25 USD/mes proyectados) |
| Después | Anotar los resultados en `docs/validation-results.md` (T038) y conectar Power BI (`docs/powerbi-setup.md`) |

---

## Paso 11 — Detener o eliminar todo

**Pausar el coste de la EC2** (el disco sigue costando ~2 USD/mes):

```bash
aws ec2 stop-instances --instance-ids "$INSTANCE_ID"     # detener
aws ec2 start-instances --instance-ids "$INSTANCE_ID"    # reanudar; Airflow arranca solo
```

**Eliminar la orquestación** (EC2, rol y security group):

```bash
terraform -chdir=infra/airflow destroy -var "bucket_name=$BUCKET"
```

**Eliminar el resto** (borra los datos de forma irreversible):

```bash
aws lambda delete-function --function-name birds-inaturalist-ingestion
aws iam delete-role-policy --role-name birds-ingestion-lambda-role --policy-name birds-ingestion
aws iam delete-role --role-name birds-ingestion-lambda-role
aws cloudwatch delete-alarms --alarm-names birds-ingestion-errors birds-ingestion-duration
aws events remove-targets --rule birds-ingestion-daily --ids 1 && aws events delete-rule --name birds-ingestion-daily
aws sns delete-topic --topic-arn "$TOPIC_ARN"
aws ssm delete-parameter --name /birds-pipeline/last_successful_run_date
aws glue delete-database --name birds_dbt && aws glue delete-database --name birds_raw
aws s3 rm "s3://$BUCKET" --recursive && aws s3api delete-bucket --bucket "$BUCKET"
```

---

## Problemas frecuentes

| Síntoma | Causa probable | Solución |
|---------|----------------|----------|
| `aws ssm start-session` → *TargetNotConnected* | El agente aún no se registró o la instancia está arrancando | Esperar 3–5 min; comprobar en **Systems Manager → Fleet Manager** |
| El bootstrap se detiene en `pip install` o aparece `Killed` | Memoria insuficiente (2 GB) | Revisar `free -m`; relanzar `sudo bash /var/lib/cloud/instance/scripts/part-001` (es idempotente); plan B: `instance_type = "t4g.small"` con AMI arm64 o t3.medium |
| `terraform init` falla con "no space left on device" | Disco local lleno | Liberar ≥ 1,5 GB |
| Lambda: `Task timed out after 180 seconds` | Se invocó sin watermark | Hacer la carga inicial del paso 4 |
| Athena: `INVALID_CAST_ARGUMENT` en `created_at` | El formato ISO 8601 de iNaturalist (`2024-05-01T10:23:45+02:00`) podría no aceptarse en `CAST(... AS TIMESTAMP)` | Cambiar en `stg_inaturalist__observations.sql` a `from_iso8601_timestamp(created_at)` (cambio de la 001, con su PR) |
| dbt: `AccessDenied` | Falta un permiso en el rol de Airflow | Ver el paso 8 |
| No llegan los emails | Suscripción SNS sin confirmar | Paso 2.3 |

---

## Cambios pendientes detectados al preparar esta guía

1. **Registro de la tabla raw (feature 001).** `stage_external_sources` no funciona con Athena
   (ver el paso 5). Propuesta: versionar el DDL con partition projection como macro de dbt
   (`dbt run-operation create_raw_observations_table`), retirar `dbt_external_tables` de
   `packages.yml` y corregir el README y el quickstart de la 001.
2. **Carga inicial.** Documentar en la spec 001 que la primera carga se hace fuera de Lambda
   (paso 4), o permitir que la ingesta trabaje por tramos de fechas.
