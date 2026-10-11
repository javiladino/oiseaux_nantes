# Operación de Airflow — Pipeline de Aves de Nantes

Guía para operar el orquestador desplegado en la feature `002-airflow-orchestration`: acceso,
despliegue, ejecuciones manuales, recuperación de fallos y reversión.

| Elemento | Valor |
|----------|-------|
| Instancia | EC2 `birds-airflow` (t3.small, Amazon Linux 2023, `eu-west-3`) |
| DAG | `nantes_birds_pipeline`, diario a las 05:00 UTC |
| Repositorio en la instancia | `/opt/oiseaux_nantes` (rama `main`) |
| Configuración y secretos | `/opt/airflow/airflow.cfg`, `/etc/airflow/airflow.env` (modo 600) |
| Logs | `/opt/airflow/logs`, `journalctl -u airflow-*`, `/var/log/airflow-bootstrap.log` |
| Alertas | Topic SNS `birds-pipeline-alerts` → email del responsable |

---

## 1. Acceder a la UI

La instancia no tiene puertos de entrada. Se accede con port forwarding de Session Manager
(requiere el [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)
en tu máquina):

```bash
terraform -chdir=infra/airflow output -raw ui_tunnel_command | sh
# Navegador: http://localhost:8080
```

**Usuario**: `admin`. **Contraseña**: generada en el primer arranque. Para verla:

```bash
aws ssm start-session --target "$(terraform -chdir=infra/airflow output -raw instance_id)"
sudo cat /opt/airflow/simple_auth_manager_passwords.json.generated
```

## 2. Desplegar cambios

Tras fusionar en `main` cambios del DAG, de los plugins o de los modelos dbt:

```bash
aws ssm start-session --target <instance_id>
sudo -u airflow /opt/oiseaux_nantes/orchestration/deploy/deploy.sh
```

`deploy.sh` hace `git pull`, `dbt deps` y `dbt parse` (regenera el manifest que usa Cosmos). El
`dag-processor` recarga el DAG en ≤ 5 min; no hace falta reiniciar servicios.

Si cambian `airflow.cfg.template`, las unidades systemd o `orchestration/requirements.txt`, hay
que aplicar el cambio a mano en la instancia (o volver a ejecutar
`orchestration/bootstrap/install_airflow.sh`, que es idempotente) y reiniciar los servicios:

```bash
sudo systemctl restart airflow-api-server airflow-scheduler airflow-dag-processor
```

## 3. Ejecuciones manuales

Todas las órdenes `airflow` se ejecutan en la instancia como el usuario `airflow` con su entorno:

```bash
sudo -u airflow bash -c 'set -a; source /etc/airflow/airflow.env; set +a; /opt/airflow-venv/bin/airflow <orden>'
```

| Objetivo | Orden |
|----------|-------|
| Ejecución normal | `airflow dags trigger nantes_birds_pipeline` |
| Reconstrucción completa de dbt | `airflow dags trigger nantes_birds_pipeline --conf '{"full_refresh": true}'` |
| Probar el DAG sin el scheduler (aunque esté pausado) | `airflow dags test nantes_birds_pipeline` |
| Ver las últimas ejecuciones | `airflow dags list-runs nantes_birds_pipeline --limit 5` |

La reconstrucción completa solo afecta a los modelos dbt: la ingesta sigue siendo incremental y
el watermark no se toca. Nunca hay dos ejecuciones a la vez; una nueva espera en cola.

## 4. Recuperar una ejecución fallida

1. Leer el email de alerta: indica la tarea, el intento y el error.
2. En la UI, abrir la ejecución → tarea en rojo → **Logs**.
3. Corregir la causa (datos, permisos, código + `deploy.sh`).
4. Seleccionar la tarea fallida → **Clear** (con *Downstream*) para relanzarla junto a las que
   quedaron en `upstream_failed`.

La ingesta y los modelos son idempotentes: relanzar no genera duplicados.

## 5. Re-ingesta histórica (excepcional)

No forma parte del DAG (decisión de la spec 002, opción A). Solo si hay que volver a descargar
todo el histórico de iNaturalist, con justificación (constitución II):

```bash
aws ssm delete-parameter --name /birds-pipeline/last_successful_run_date
# Después, una ejecución con reconstrucción completa:
airflow dags trigger nantes_birds_pipeline --conf '{"full_refresh": true}'
```

Los archivos raw duplicados que genere se deduplican en staging por `observation_id`.

## 6. Revertir a EventBridge

Si hay que desactivar Airflow temporalmente:

```bash
airflow dags pause nantes_birds_pipeline
aws events enable-rule --name birds-ingestion-daily --region eu-west-3
```

Con EventBridge solo se ejecuta la ingesta; dbt vuelve a ser manual. Para volver a Airflow,
invertir las dos órdenes (`disable-rule` + `dags unpause`) en el mismo paso, de modo que nunca
haya dos programadores activos.

## 7. Problemas frecuentes

| Síntoma | Causa probable | Acción |
|---------|----------------|--------|
| Servicios reiniciándose, `Killed` en `journalctl` | Falta de memoria (2 GB) | Comprobar `free -m` y la swap; bajar `parallelism`; si persiste, plan B: `instance_type = "t4g.small"` (AMI arm64) o t3.medium |
| `AccessDenied` en una tarea dbt | Falta una acción IAM para dbt-athena | Añadir la acción mínima a `contracts/iam-policy.md` y `infra/airflow/iam.tf`, `terraform apply` |
| El DAG no aparece o muestra error de importación | Falta el manifest o error de código | `deploy.sh`; `airflow dags list-import-errors` |
| `ingest_inaturalist` falla con `Lambda function execution resulted in error` | Error dentro de la Lambda | Revisar los logs de CloudWatch de `birds-inaturalist-ingestion` |
| No llegan alertas | Suscripción SNS sin confirmar o `BIRDS_ALERTS_TOPIC_ARN` incorrecto | Confirmar la suscripción por email; revisar `/etc/airflow/airflow.env` |
