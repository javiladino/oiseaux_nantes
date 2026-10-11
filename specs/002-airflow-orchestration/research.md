# Investigación: Orquestación del Pipeline con Apache Airflow

**Feature**: `002-airflow-orchestration` | **Fecha**: 2026-10-11

Todos los puntos NEEDS CLARIFICATION del Contexto Técnico se resuelven a continuación.

---

## 1. Versión de Airflow

### Decisión
**Apache Airflow 3.3.2** (última versión estable en PyPI), instalada con el archivo de
constraints oficial de esa versión y Python 3.12.

### Justificación
- Airflow 2.x llegó a fin de vida el 22 de abril de 2026 (2.11.2 fue el último parche); empezar
  un proyecto nuevo en 2.x no tiene sentido.
- La línea 3.3 está publicada desde julio de 2026 (3.3.1 el 12 de agosto, 3.3.2 después), con
  tiempo suficiente de estabilización.
- `requires_python` de 3.3.2 es `>=3.10, !=3.15`; Python 3.12 está disponible en Amazon Linux 2023.

### Implicaciones de Airflow 3
- El antiguo `webserver` pasa a ser `api-server`; el `dag-processor` es un proceso independiente
  y obligatorio.
- Los SLA de Airflow 2 desaparecen; su sustituto son las **Deadline Alerts** (ver §7).
- Los imports de DAG usan `airflow.sdk` (`from airflow.sdk import dag, task`).

### Alternativas consideradas
- Airflow 2.11: sin soporte desde abril de 2026; descartado.
- MWAA (Airflow gestionado): ~350 USD/mes o más; incumple SC-007 y la constitución IV; descartado.

---

## 2. Forma de despliegue en la EC2

### Decisión
Instalación **nativa con pip en un virtualenv** + **PostgreSQL local** + **LocalExecutor** +
**unidades systemd** (`airflow-api-server`, `airflow-scheduler`, `airflow-dag-processor`),
sobre **Amazon Linux 2023**, instancia **t3.small** (2 vCPU, 2 GB) con **2 GB de swap** y
límites de concurrencia bajos.

### Justificación
- El `docker-compose.yaml` oficial usa CeleryExecutor + Redis + workers + triggerer: demasiado
  para 2 GB de RAM y para un DAG diario de ~10 tareas.
- LocalExecutor ejecuta las tareas como subprocesos del scheduler: sin broker ni workers extra.
- LocalExecutor no admite SQLite → PostgreSQL local (paquete `postgresql16-server` de AL2023);
  sin RDS para no añadir coste (~15 USD/mes más).
- systemd reinicia los procesos si caen y los arranca con la instancia (caso límite de la spec).
- Ajustes de memoria: `parallelism=4`, `max_active_tasks_per_dag=4`, `max_active_runs_per_dag=1`,
  1 worker del api-server, `[dag_processor] refresh_interval` alto.

### Coste estimado (eu-west-3, bajo demanda)
| Recurso | Coste mensual aprox. |
|---------|----------------------|
| t3.small 24/7 | ~17 USD |
| EBS gp3 20 GB | ~2 USD |
| **Total** | **~19 USD** (cumple SC-007 ≤ 25 USD) |

Si aparecen errores de memoria (OOM), el plan B es **t4g.small** (ARM Graviton, misma RAM, ~12
USD/mes) con más swap, o t3.medium aceptando superar el límite de SC-007 con una enmienda de la spec.

### Alternativas consideradas
- docker-compose oficial: consumo de memoria excesivo; descartado.
- Astro CLI en la EC2: pensado para desarrollo local y Astro Cloud, añade Docker; descartado.
- RDS PostgreSQL para metadatos: coste adicional injustificado para un único DAG; descartado.

---

## 3. Integración de dbt (Astronomer Cosmos)

### Decisión
**astronomer-cosmos 1.15.x** con `DbtTaskGroup`, en modo de ejecución **LOCAL** con dbt
instalado en un **virtualenv separado** (`/opt/dbt-venv`, `dbt-athena-community`) y
`ExecutionConfig(dbt_executable_path=...)`. Carga del proyecto con **`LoadMode.DBT_MANIFEST`**
a partir de `target/manifest.json` generado en el despliegue con `dbt deps && dbt parse`.
Comportamiento de tests **`TestBehavior.AFTER_EACH`** (valor por defecto).

### Justificación
- Cosmos 1.15.1 declara `apache-airflow>=2.9.0` y es compatible con Airflow 3.
- El virtualenv separado evita conflictos de dependencias entre Airflow y dbt (recomendación de
  Cosmos).
- `AFTER_EACH` crea por cada modelo una tarea `run` seguida de su `test`; los modelos dependientes
  solo se ejecutan si los tests del anterior pasan → cumple FR-005 y FR-006.
- `DBT_MANIFEST` evita ejecutar `dbt ls` cada vez que se parsea el DAG: crítico con 2 GB de RAM.
- `dbt parse` no necesita conexión a Athena, así que el manifest también puede generarse en CI.

### Reconstrucción completa (FR-009, opción A de la clarificación)
Parámetro del DAG `full_refresh: bool = False` pasado a Cosmos mediante
`operator_args={"full_refresh": "{{ params.full_refresh }}"}`. Solo afecta a dbt
(`--full-refresh`); la tarea de ingesta no recibe el parámetro.

**Verificado en la implementación (código fuente de Cosmos)**: `full_refresh` está en
`template_fields` de `DbtRunMixin`; el valor renderizado se convierte con `to_boolean`, así que
la cadena `"False"` no añade el flag; los operadores de test lo descartan sin error
(`AbstractDbtBase` hace `kwargs.pop("full_refresh")`). No hace falta
`render_template_as_native_obj`. Además, `ProjectConfig(install_dbt_deps=False)` evita ejecutar
`dbt deps` en cada tarea, porque `deploy.sh` ya lo hace.

### Alternativas consideradas
- `BashOperator` con `dbt build`: una sola tarea opaca; incumple FR-005; descartado.
- `ExecutionMode.VIRTUALENV` (Cosmos crea el venv en cada tarea): lento y costoso en memoria; descartado.
- `LoadMode.DBT_LS`: ejecuta dbt en cada parseo del DAG; descartado por memoria y tiempo.

---

## 4. Invocación de la Lambda

### Decisión
`LambdaInvokeFunctionOperator` (provider `apache-airflow-providers-amazon`) con
`invocation_type="RequestResponse"`, `payload="{}"` y `log_type="Tail"`.

### Justificación
- El operador lanza `ValueError("Lambda function execution resulted in error", ...)` cuando la
  respuesta contiene `FunctionError` (verificado en el código fuente del provider) → cumple
  FR-003 sin código adicional.
- La Lambda tiene un timeout de 3 minutos, por debajo del read timeout de botocore (60 s por
  defecto, ampliable): configurar `botocore_config={"read_timeout": 200,
  "connect_timeout": 10, "retries": {"max_attempts": 0}}` para que el cliente no se desconecte
  mientras espera y los reintentos los gestione Airflow, no botocore.
- La Lambda es idempotente (watermark en SSM, deduplicación en staging), así que los reintentos
  de Airflow son seguros.

---

## 5. Credenciales y permisos

### Decisión
**Instance profile** en la EC2 (sin claves estáticas). La conexión `aws_default` de Airflow no
lleva credenciales y usa la cadena por defecto de boto3. Un único rol `birds-airflow-ec2-role`
con políticas en línea limitadas a ARNs concretos (ver `contracts/iam-policy.md`).

### Justificación
- Cumple FR-014 y la constitución IV: sin secretos en disco ni en variables de Airflow.
- dbt-athena usa la misma cadena de credenciales de boto3.

### Excepción justificada: Session Manager
El acceso sin puertos abiertos (FR-015) usa **AWS Systems Manager Session Manager** con
*port forwarding* al puerto 8080. El agente SSM necesita la política gestionada
`AmazonSSMManagedInstanceCore`, cuyas acciones `ssmmessages:*` y `ec2messages:*` **no admiten
permisos a nivel de recurso** (solo `Resource: "*"`). Se documenta en Complexity Tracking del plan.

### Alternativas consideradas
- Túnel SSH con el puerto 22 abierto a una IP: evita el comodín IAM, pero expone un puerto,
  exige gestionar claves y la IP del responsable puede cambiar; descartado.
- Exponer la UI con ALB + autenticación: coste (~18 USD/mes) y superficie de ataque; descartado.

---

## 6. Alertas

### Decisión
`on_failure_callback` a nivel de tarea que publica en el topic SNS existente
`birds-pipeline-alerts` (feature 001) mediante `SnsHook`, con un mensaje estructurado (ver
`contracts/alert-message.md`). Se dispara solo cuando la tarea falla definitivamente (tras agotar
los reintentos).

### Justificación
- Reutiliza la suscripción por email ya configurada; solo añade `sns:Publish` sobre ese ARN.
- La publicación es inmediata → SC-003 (< 15 min) se cumple con margen.
- La alarma de CloudWatch sobre la Lambda se mantiene como respaldo independiente de Airflow.

### Alternativas consideradas
- SMTP desde Airflow: requiere un servidor de correo y credenciales; descartado.
- Solo la alarma de CloudWatch: no cubre fallos de dbt ni del propio Airflow; descartado.

---

## 7. Detección de retrasos (caso límite de las 08:00 UTC)

### Decisión
**Deadline Alert** a nivel de DAG: si una ejecución no ha terminado 2 horas después de su hora
programada (07:00 UTC), se envía una alerta por el mismo canal SNS.

### Justificación
- Es el mecanismo que sustituye a los SLA en Airflow 3 y avisa antes de la actualización de
  Power BI de las 08:00 UTC (SC-001).
- **Verificado en la documentación de Airflow 3.3.2**: `from airflow.sdk import DeadlineAlert,
  DeadlineReference, SyncCallback`; `DeadlineAlert(reference=DeadlineReference.DAGRUN_LOGICAL_DATE,
  interval=timedelta(hours=2), callback=SyncCallback(...))`. Se usa `SyncCallback` (disponible
  desde 3.2), que se envía al executor por defecto (LocalExecutor); `AsyncCallback` requeriría
  el proceso `triggerer`, que no se despliega.
- Las Deadline Alerts están marcadas como **experimentales**. Queda por confirmar en el
  Escenario 7 de `quickstart.md` que los `kwargs` con plantillas Jinja se renderizan en
  `SyncCallback`; si no, `notify_deadline` también acepta `context` y en el peor caso el email
  llega sin `run_id`.

---

## 8. Infraestructura como código

### Decisión
**Terraform** en `infra/airflow/` para: rol IAM + instance profile, security group sin reglas
de entrada, instancia EC2 con `user_data` que ejecuta el script de bootstrap, y volumen EBS gp3
cifrado. La desactivación de la regla de EventBridge se hace con una orden de AWS CLI
documentada (y reversible) para no importar recursos creados a mano en la feature 001.

### Justificación
- La constitución ya incluye Terraform en el stack; EC2 + IAM + SG + instance profile son
  suficientes recursos como para que la reproducibilidad compense.
- El estado de Terraform es local (ya ignorado en `.gitignore`); un backend remoto queda fuera
  de la v1.

### Alternativas consideradas
- Solo AWS CLI (como en la 001): más rápido de escribir, pero difícil de reproducir y de destruir
  limpiamente; descartado.
- CloudFormation: válido, pero la constitución ya nombra Terraform; descartado.

---

## 9. Despliegue del código en la instancia

### Decisión
El repositorio se clona en `/opt/oiseaux_nantes` durante el bootstrap. El despliegue de cambios
se hace con un script `orchestration/deploy/deploy.sh` (ejecutado vía Session Manager o
`aws ssm send-command`) que hace `git pull` de `main`, `dbt deps && dbt parse` y deja que el
`dag-processor` recargue el DAG.

### Justificación
- Un único DAG con cambios poco frecuentes no justifica un pipeline de CD.
- `dbt parse` regenera `manifest.json`, del que depende `LoadMode.DBT_MANIFEST`.

---

## 10. Validación en CI

### Decisión
Nuevo workflow `.github/workflows/airflow_ci.yml` (en PRs que tocan `orchestration/**` o
`dbt_birds/**`) que instala Airflow 3.3.2 con constraints, Cosmos y dbt, ejecuta `dbt parse`
con un perfil ficticio y lanza `pytest tests/orchestration/` con un test de integridad
(`DagBag` sin errores de importación, estructura de tareas y parámetros esperados).

### Justificación
- Cumple FR-018: un DAG que no carga no llega a `main`.
- No necesita credenciales de AWS: ni `dbt parse` ni el parseo del DAG se conectan a Athena.

---

## Tabla Resumen

| Pregunta | Respuesta |
|----------|-----------|
| Versión de Airflow | 3.3.2 con constraints, Python 3.12 |
| Ejecutor | LocalExecutor |
| Base de metadatos | PostgreSQL 16 local en la EC2 |
| Instancia | t3.small + 2 GB de swap, Amazon Linux 2023 (plan B: t4g.small) |
| Coste estimado | ~19 USD/mes |
| Integración dbt | Cosmos 1.15.x, `DbtTaskGroup`, LOCAL + venv separado, `DBT_MANIFEST`, tests `AFTER_EACH` |
| Invocación de la Lambda | `LambdaInvokeFunctionOperator`, `RequestResponse` (lanza error ante `FunctionError`) |
| Credenciales | Instance profile, sin claves estáticas |
| Acceso a la UI | Session Manager con port forwarding, sin puertos de entrada |
| Alertas | `on_failure_callback` → SNS `birds-pipeline-alerts` + Deadline Alert a las 07:00 UTC |
| IaC | Terraform en `infra/airflow/` |
| Despliegue | `git pull` + `dbt parse` con `deploy.sh` |
| CI | `airflow_ci.yml` con test de integridad del DAG |
