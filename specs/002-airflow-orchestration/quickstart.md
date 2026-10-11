# Guía de Validación Rápida: Orquestación con Apache Airflow

**Feature**: `002-airflow-orchestration` | **Fecha**: 2026-10-11

Escenarios ejecutables que demuestran que la orquestación funciona de extremo a extremo. No es
una guía de implementación: el DAG está descrito en
[contracts/dag-interface.md](contracts/dag-interface.md), los permisos en
[contracts/iam-policy.md](contracts/iam-policy.md) y las alertas en
[contracts/alert-message.md](contracts/alert-message.md).

---

## Requisitos Previos

| Requisito | Comprobación |
|-----------|--------------|
| Feature 001 desplegada (Lambda, S3, Glue, Athena, SNS) | `aws lambda get-function --function-name birds-inaturalist-ingestion` |
| Constitución en la versión 1.1.0 | Última línea de `.specify/memory/constitution.md` |
| Terraform ≥ 1.6 y AWS CLI configurados en `eu-west-3` | `terraform version && aws sts get-caller-identity` |
| Plugin de Session Manager para AWS CLI | `session-manager-plugin --version` |
| Instancia desplegada | `cd infra/airflow && terraform apply` → output `instance_id` |

Abrir la UI de Airflow (se usa en varios escenarios):

```bash
aws ssm start-session --target <instance_id> \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8080"],"localPortNumber":["8080"]}'
# Navegador: http://localhost:8080
```

---

## Escenario 0: Validación Local del DAG (sin AWS)

**Qué demuestra**: FR-018, el contrato de `dag-interface.md`

```bash
pip install -r orchestration/requirements.txt \
  --constraint https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.12.txt
pip install -r tests/requirements-dev.txt \
  --constraint https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.12.txt
python -m venv /tmp/dbt-venv && /tmp/dbt-venv/bin/pip install dbt-athena-community   # dbt aparte, como en la EC2
export DBT_EXECUTABLE_PATH=/tmp/dbt-venv/bin/dbt
export BIRDS_S3_BUCKET=ci-placeholder   # sources.yml exige esta variable
cd dbt_birds && $DBT_EXECUTABLE_PATH deps \
  && $DBT_EXECUTABLE_PATH parse --profiles-dir ../orchestration/config --target ci && cd ..
pytest tests/orchestration/ -v
# Esperado: todos los tests pasan; DagBag sin errores de importación
```

---

## Escenario 1: Servicios de Airflow Operativos (Infraestructura)

**Qué demuestra**: FR-013, FR-015

```bash
# 1. Servicios activos en la instancia (desde una sesión de Session Manager)
sudo systemctl is-active airflow-api-server airflow-scheduler airflow-dag-processor postgresql
# Esperado: active ×4

# 2. Sin puertos de entrada
aws ec2 describe-security-groups --group-names birds-airflow-sg \
  --query 'SecurityGroups[0].IpPermissions'
# Esperado: []

# 3. El DAG está cargado
airflow dags list | grep nantes_birds_pipeline
# Esperado: nantes_birds_pipeline aparece, sin errores de importación
```

### Resultado Esperado
- Los cuatro servicios activos y configurados para arrancar con la instancia
- UI accesible solo a través del túnel de Session Manager

---

## Escenario 2: Ejecución Diaria Completa (Historia 1)

**Qué demuestra**: FR-001 a FR-005, SC-001, SC-008

Antes de pasar a producción (DAG todavía pausado, EventBridge activo), validar con
`airflow dags test nantes_birds_pipeline`, que ejecuta el DAG completo sin el scheduler. Una vez
desactivado EventBridge y reactivado el DAG (T022):

```bash
# 1. Disparar una ejecución equivalente a la programada
airflow dags trigger nantes_birds_pipeline

# 2. Seguir el estado
airflow dags list-runs nantes_birds_pipeline --limit 1
# Esperado: state=success
```

En la UI (vista Graph / Grid):
- `ingest_inaturalist` en verde, con el payload `Ingested N observations` en XCom
- Grupo `dbt_medallion` con una pareja `run`/`test` por cada uno de los 6 modelos, en verde y en
  el orden del contrato
- Duración total < 30 min

### Resultado Esperado
- La ejecución termina en `success` sin intervención manual
- Los modelos de marts se actualizan (comprobar con Athena:
  `SELECT MAX(created_at_utc) FROM birds_dbt.fct_observations`)

---

## Escenario 3: Contención de Fallos y Alertas (Historia 2)

**Qué demuestra**: FR-003, FR-006, FR-007, FR-008, SC-002, SC-003

### 3a. Fallo en la ingesta

```bash
# 1. Forzar el fallo de la invocación: concurrencia reservada a 0 (toda invocación se rechaza)
aws lambda put-function-concurrency --function-name birds-inaturalist-ingestion \
  --reserved-concurrent-executions 0

# 2. Disparar el DAG y esperar ~15 min (2 reintentos × 5 min)
airflow dags trigger nantes_birds_pipeline

# 3. Restaurar la concurrencia
aws lambda delete-function-concurrency --function-name birds-inaturalist-ingestion
```

Nota: este escenario prueba un fallo de invocación. El caso en que la Lambda se ejecuta pero
devuelve `FunctionError` (FR-003) se cubre con un test unitario del DAG que simula esa respuesta.

**Esperado**:
- `ingest_inaturalist`: 3 intentos y estado `failed`
- Todas las tareas de `dbt_medallion` en `upstream_failed` (ninguna se ejecuta)
- Un único email con asunto `[birds-pipeline] FALLO ingest_inaturalist (...)` en < 15 min desde el último intento
- El watermark de SSM no cambia

### 3b. Fallo de un test de dbt

Introducir temporalmente en Athena un registro fuera del bbox no es posible sin tocar raw; en su
lugar, en un entorno de prueba, cambiar el límite del test singular
`assert_observations_within_nantes_bbox.sql` para que falle, desplegar con `deploy.sh` y disparar.

**Esperado**:
- `…int_observations__geospatial_enriched.test` en `failed`
- Las dimensiones y `fct_observations` en `upstream_failed`
- Email de alerta que nombra la tarea de test fallida
- Revertir el cambio y relanzar con *Clear* → la ejecución termina en `success` sin duplicados (FR-006, Historia 2 escenario 4)

---

## Escenario 4: Reconstrucción Completa Bajo Demanda (Historia 3)

**Qué demuestra**: FR-009, FR-010, SC-006

```bash
# 1. Guardar el watermark actual
aws ssm get-parameter --name /birds-pipeline/last_successful_run_date --query Parameter.Value

# 2. Disparar con reconstrucción completa
airflow dags trigger nantes_birds_pipeline --conf '{"full_refresh": true}'

# 3. Mientras se ejecuta, disparar otra ejecución normal
airflow dags trigger nantes_birds_pipeline
airflow dags list-runs nantes_birds_pipeline --limit 2
# Esperado: la segunda queda en "queued" hasta que termine la primera

# 4. Al terminar, comprobar el watermark
aws ssm get-parameter --name /birds-pipeline/last_successful_run_date --query Parameter.Value
# Esperado: solo cambia si la ingesta incremental trajo observaciones nuevas (nunca se reinicia)
```

En los logs de `dbt_medallion.fct_observations.run` debe aparecer `--full-refresh`.

En Athena:

```sql
SELECT COUNT(*), COUNT(DISTINCT observation_id) FROM birds_dbt.fct_observations;
-- Esperado: ambos recuentos iguales
```

---

## Escenario 5: Mínimo Privilegio (IAM)

**Qué demuestra**: FR-014, constitución IV

```bash
ROLE_ARN=$(terraform -chdir=infra/airflow output -raw role_arn)

aws iam simulate-principal-policy --policy-source-arn "$ROLE_ARN" \
  --action-names lambda:InvokeFunction \
  --resource-arns arn:aws:lambda:eu-west-3:<account-id>:function:birds-inaturalist-ingestion \
  --query 'EvaluationResults[0].EvalDecision'
# Esperado: "allowed"

aws iam simulate-principal-policy --policy-source-arn "$ROLE_ARN" \
  --action-names s3:PutObject \
  --resource-arns arn:aws:s3:::<bucket>/raw/inaturalist/observations/x.json \
  --query 'EvaluationResults[0].EvalDecision'
# Esperado: "implicitDeny"

aws iam simulate-principal-policy --policy-source-arn "$ROLE_ARN" \
  --action-names ssm:GetParameter \
  --resource-arns arn:aws:ssm:eu-west-3:<account-id>:parameter/birds-pipeline/last_successful_run_date \
  --query 'EvaluationResults[0].EvalDecision'
# Esperado: "implicitDeny"
```

---

## Escenario 6: Un Único Programador y Recuperación tras Parada

**Qué demuestra**: FR-011, FR-012, SC-005

```bash
# 1. La regla de EventBridge está desactivada
aws events describe-rule --name birds-ingestion-daily --query State
# Esperado: "DISABLED"

# 2. Simular una parada durante la hora programada
aws ec2 stop-instances --instance-ids <instance_id>
# ... esperar a que pase una hora programada (o cambiar temporalmente el cron) ...
aws ec2 start-instances --instance-ids <instance_id>

# 3. Al arrancar, revisar las ejecuciones
airflow dags list-runs nantes_birds_pipeline --limit 3
# Esperado: solo una ejecución nueva para el intervalo más reciente, sin ejecuciones atrasadas acumuladas
```

---

## Escenario 7: Alerta de Retraso

**Qué demuestra**: caso límite de las 08:00 UTC, SC-001

En un entorno de prueba, reducir temporalmente la Deadline Alert a 1 minuto, añadir un
`sleep` a una ejecución manual o pausar el scheduler tras iniciarla, y comprobar que llega un
email con asunto `[birds-pipeline] RETRASO nantes_birds_pipeline (...)`. Restaurar la
configuración después.

---

## Validación en CI

Cada PR que modifica `orchestration/**` o `dbt_birds/**` ejecuta `.github/workflows/airflow_ci.yml`:

```yaml
- run: dbt parse            # perfil ficticio, sin conexión a AWS
- run: pytest tests/orchestration/ -v
```

Un DAG que no carga o que rompe el contrato bloquea el merge (FR-018).
