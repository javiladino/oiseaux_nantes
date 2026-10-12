---

description: "Lista de tareas para la orquestación del pipeline con Apache Airflow"
---

# Tareas: Orquestación del Pipeline con Apache Airflow

**Entrada**: Documentos de diseño en `/specs/002-airflow-orchestration/`

**Requisitos previos**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓, quickstart.md ✓

**Tests**: Incluidos — FR-018 exige validar automáticamente el DAG en CI; el contrato
[dag-interface.md](contracts/dag-interface.md) marca con ✔ lo que el test de integridad debe comprobar.

**Organización**: Las tareas se agrupan por historia de usuario para poder implementar y probar
cada historia de forma independiente.

## Formato: `[ID] [P?] [Story?] Descripción`

- **[P]**: Puede ejecutarse en paralelo (archivos distintos, sin dependencias)
- **[Story]**: Historia de usuario a la que pertenece la tarea (US1, US2, US3)
- Cada descripción incluye las rutas exactas de los archivos

## Convenciones de Rutas

- `orchestration/` — DAG, plugins, configuración, systemd, bootstrap y despliegue de Airflow
- `infra/airflow/` — Terraform de la EC2, IAM y security group
- `tests/orchestration/` — tests del DAG
- `.github/workflows/` — CI
- `docs/` — documentación
- `ingestion/` y `dbt_birds/` — **no se modifican** en esta feature

---

## Phase 1: Setup (Infraestructura Compartida)

**Propósito**: Enmienda de la constitución, estructura de directorios y dependencias

- [X] T001 Enmendar `.specify/memory/constitution.md` a la versión **1.1.0** (MINOR, FR-017): en la tabla del Stack Tecnológico, cambiar la fila "Programador" a "Apache Airflow 3.3 (EC2) — orquestación diaria de ingesta y transformación; EventBridge queda desactivado" y añadir la fila "Orquestación | Apache Airflow 3.3 + Astronomer Cosmos | DAG diario, dependencias, reintentos, alertas"; en el Principio IV añadir que el rol del orquestador solo puede invocar la Lambda de ingesta y acceder a Athena/Glue/S3 sobre los recursos del proyecto, sin ARNs comodín, con la única excepción de la política gestionada `AmazonSSMManagedInstanceCore` (sus acciones no admiten permisos por recurso), y aclarar que un comodín de sufijo dentro de un recurso concreto (p. ej. `raw/inaturalist/observations/*` o `table/birds_dbt/*`) no se considera ARN comodín; en el Principio I añadir que el orquestador no extrae ni transforma datos; actualizar el Sync Impact Report (1.0.0 → 1.1.0) y la última línea a `**Version**: 1.1.0 | **Ratified**: 2026-10-10 | **Last Amended**: 2026-10-11`
- [X] T002 Crear la estructura de directorios: `orchestration/dags/`, `orchestration/plugins/`, `orchestration/config/`, `orchestration/systemd/`, `orchestration/bootstrap/`, `orchestration/deploy/`, `infra/airflow/`, `tests/orchestration/`
- [X] T003 [P] Crear `orchestration/requirements.txt` con `apache-airflow==3.3.2`, `apache-airflow-providers-amazon` y `astronomer-cosmos~=1.15`, con un comentario en cabecera que indique instalarlo siempre con `--constraint https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.12.txt`; dbt **no** va aquí (vive en un virtualenv aparte)
- [X] T004 [P] Añadir a `.gitignore`: `infra/airflow/*.tfvars` y `infra/airflow/.terraform/` (el archivo `.terraform.lock.hcl` sí se versiona)
- [X] T005 [P] Crear `orchestration/config/profiles.yml` con el perfil `birds_pipeline` y dos targets: `prod` (`type: athena`, `region_name: eu-west-3`, `database: awsdatacatalog`, `schema: birds_dbt`, `threads: 4`, `s3_staging_dir: "s3://{{ env_var('BIRDS_S3_BUCKET') }}/athena-results/"`, `s3_data_dir: "s3://{{ env_var('BIRDS_S3_BUCKET') }}/processed/"`) y `ci` con los mismos campos pero valores ficticios fijos (`s3://ci-placeholder/...`), usado solo por `dbt parse` sin conexión a AWS

---

## Phase 2: Foundational (Requisitos Previos Bloqueantes)

**Propósito**: Instancia EC2 con Airflow instalado y funcionando, y la base de los tests — necesario antes de cualquier historia de usuario

**⚠️ CRÍTICO**: Ningún trabajo de historias de usuario puede empezar hasta completar esta fase

- [X] T006 Crear `infra/airflow/versions.tf`: `required_version = ">= 1.6"`, provider `hashicorp/aws` `~> 6.0`, `provider "aws" { region = var.region }` con `default_tags` `{ project = "oiseaux-nantes", component = "airflow" }`
- [X] T007 [P] Crear `infra/airflow/variables.tf`: `region` (por defecto `eu-west-3`), `instance_type` (por defecto `t3.small`), `volume_size_gb` (por defecto `20`), `bucket_name` (obligatoria), `lambda_function_name` (por defecto `birds-inaturalist-ingestion`), `alerts_topic_name` (por defecto `birds-pipeline-alerts`), `repo_url` (por defecto `https://github.com/javiladino/oiseaux_nantes.git`), `repo_branch` (por defecto `main`)
- [X] T008 Crear `infra/airflow/iam.tf` según [contracts/iam-policy.md](contracts/iam-policy.md): rol `birds-airflow-ec2-role` asumible por `ec2.amazonaws.com`; política en línea `birds-airflow-orchestration` con las 7 sentencias del contrato (`InvokeIngestionLambda`, `AthenaPrimaryWorkgroup`, `GlueCatalogBirds`, `S3ListBucket`, `S3ReadRaw`, `S3ReadWriteProcessedAndResults`, `PublishAlerts`) construyendo los ARNs con `data "aws_caller_identity"` y las variables; adjuntar `arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore`; instance profile `birds-airflow-ec2-profile`. **Sin** permisos sobre SSM Parameter Store ni `s3:PutObject` en `raw/`
- [X] T009 Crear `infra/airflow/main.tf`: AMI de Amazon Linux 2023 vía `data "aws_ssm_parameter"` `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64`; VPC y subred por defecto (`data "aws_vpc" { default = true }`); security group `birds-airflow-sg` **sin reglas de entrada** y salida solo HTTPS 443 a `0.0.0.0/0`; instancia `aws_instance` con `var.instance_type`, IP pública (solo para salida), `metadata_options { http_tokens = "required" }` (IMDSv2), volumen raíz gp3 `var.volume_size_gb` cifrado, `iam_instance_profile` de T008 y `user_data = templatefile("../../orchestration/bootstrap/install_airflow.sh", {...})` pasando `bucket_name`, `alerts_topic_arn`, `repo_url`, `repo_branch`, `region`
- [X] T010 [P] Crear `infra/airflow/outputs.tf`: `instance_id`, `role_arn`, `security_group_id`, y `ui_tunnel_command` con la orden completa de `aws ssm start-session ... AWS-StartPortForwardingSession` al puerto 8080
- [X] T011 [P] Crear `orchestration/config/airflow.cfg.template` con: `[core] executor = LocalExecutor`, `dags_folder = /opt/oiseaux_nantes/orchestration/dags`, `plugins_folder = /opt/oiseaux_nantes/orchestration/plugins`, `load_examples = False`, `dags_are_paused_at_creation = True` (el DAG nace pausado para no convivir con EventBridge hasta T022), `parallelism = 4`, `max_active_tasks_per_dag = 4`, `max_active_runs_per_dag = 1`, `default_timezone = utc`; `[database] sql_alchemy_conn = postgresql+psycopg2://airflow:${AIRFLOW_DB_PASSWORD}@localhost:5432/airflow`; `[api] workers = 1`, `host = 127.0.0.1`, `port = 8080` (solo escucha en local; se accede por el túnel); `[dag_processor] refresh_interval = 300`; `[logging] base_log_folder = /opt/airflow/logs`
- [X] T012 [P] Crear las unidades systemd `orchestration/systemd/airflow-api-server.service`, `orchestration/systemd/airflow-scheduler.service` y `orchestration/systemd/airflow-dag-processor.service`: usuario `airflow`, `EnvironmentFile=/etc/airflow/airflow.env`, `ExecStart=/opt/airflow-venv/bin/airflow <api-server|scheduler|dag-processor>`, `After=network-online.target postgresql.service`, `Restart=always`, `RestartSec=10`, `WantedBy=multi-user.target`
- [X] T013 Crear `orchestration/bootstrap/install_airflow.sh` (plantilla de `templatefile`, ejecutada como `user_data`, idempotente, `set -euo pipefail`): (1) swap de 2 GB en `/swapfile` persistente en `/etc/fstab`; (2) `dnf install -y python3.12 python3.12-pip git postgresql16-server`; (3) inicializar PostgreSQL, crear usuario y base `airflow` con contraseña aleatoria; (4) crear el usuario de sistema `airflow` y clonar `repo_url`/`repo_branch` en `/opt/oiseaux_nantes`; (5) virtualenv `/opt/airflow-venv` con `orchestration/requirements.txt` y el archivo de constraints de 3.3.2 para Python 3.12; (6) virtualenv `/opt/dbt-venv` con `dbt-athena-community`; (7) escribir `/etc/airflow/airflow.env` (modo 600, propietario `airflow`) con `AIRFLOW_HOME=/opt/airflow`, `AIRFLOW_DB_PASSWORD`, `BIRDS_S3_BUCKET`, `BIRDS_ALERTS_TOPIC_ARN`, `AWS_DEFAULT_REGION`, `DBT_PROJECT_DIR=/opt/oiseaux_nantes/dbt_birds`, `DBT_PROFILES_DIR=/opt/oiseaux_nantes/orchestration/config`, `DBT_EXECUTABLE_PATH=/opt/dbt-venv/bin/dbt`, `AIRFLOW_CONN_AWS_DEFAULT='{"conn_type": "aws", "extra": {"region_name": "<region>"}}'`; (8) renderizar `airflow.cfg` desde `orchestration/config/airflow.cfg.template`; (9) `airflow db migrate`; (10) usar el auth manager por defecto de Airflow 3 (`SimpleAuthManager`) con `[core] simple_auth_manager_users = admin:admin` en `airflow.cfg`; Airflow genera la contraseña en `$AIRFLOW_HOME/simple_auth_manager_passwords.json.generated`, que debe quedar con modo 600 y propietario `airflow`; (11) ejecutar `orchestration/deploy/deploy.sh`; (12) instalar y habilitar las tres unidades systemd de T012 y `postgresql`
- [X] T014 [P] Crear `orchestration/deploy/deploy.sh` (ejecutable, `set -euo pipefail`, como usuario `airflow`): cargar `/etc/airflow/airflow.env` (necesario porque `sources.yml` y `profiles.yml` usan `env_var('BIRDS_S3_BUCKET')`), `git -C /opt/oiseaux_nantes pull --ff-only`, después en `dbt_birds/` con `/opt/dbt-venv/bin/dbt`: `dbt deps` y `dbt parse --profiles-dir ../orchestration/config --target prod` para regenerar `target/manifest.json`; no reinicia servicios (el `dag-processor` recarga el DAG solo)
- [X] T015 [P] Crear `tests/orchestration/conftest.py`: añadir `orchestration/plugins` a `sys.path`; fijar variables de entorno de prueba (`AIRFLOW_HOME` en un directorio temporal, `BIRDS_S3_BUCKET=test-bucket`, `BIRDS_ALERTS_TOPIC_ARN=arn:aws:sns:eu-west-3:000000000000:birds-pipeline-alerts`, `DBT_PROJECT_DIR=<repo>/dbt_birds`, `DBT_PROFILES_DIR=<repo>/orchestration/config`, `DBT_EXECUTABLE_PATH` = `dbt` del entorno); fixture de sesión `dagbag` = `DagBag(dag_folder="orchestration/dags", include_examples=False)` y fixture `dag` = `dagbag.get_dag("nantes_birds_pipeline")`; requiere que exista `dbt_birds/target/manifest.json` (generado con `BIRDS_S3_BUCKET=ci-placeholder dbt parse --target ci`, porque `sources.yml` exige esa variable de entorno)
- [X] T016 Desplegar la infraestructura: `terraform -chdir=infra/airflow init && terraform -chdir=infra/airflow apply -var bucket_name=<bucket>` y ejecutar el Escenario 1 de `specs/002-airflow-orchestration/quickstart.md` (servicios activos, security group sin reglas de entrada, UI accesible por el túnel)

**Punto de control**: Airflow funciona en la EC2 y la base de tests está lista — pueden empezar las historias de usuario

---

## Phase 3: User Story 1 — Ejecución Diaria Encadenada de Ingesta y Transformación (Prioridad: P1) 🎯 MVP

**Objetivo**: Un DAG diario a las 05:00 UTC invoca la Lambda de ingesta y, solo si termina bien, ejecuta los modelos dbt en orden, cada uno como tarea visible con sus tests antes de sus dependientes.

**Prueba Independiente**: Escenario 2 de `quickstart.md` — disparar el DAG y verificar que termina en `success` con `ingest_inaturalist` y las 6 parejas `run`/`test` de `dbt_medallion` en verde y en orden.

### Tests de la User Story 1

- [X] T017 [P] [US1] Escribir `tests/orchestration/test_dag_integrity.py` según los puntos ✔ de [contracts/dag-interface.md](contracts/dag-interface.md): `dagbag.import_errors == {}`; `dag_id == "nantes_birds_pipeline"`; `schedule` `"0 5 * * *"` en UTC; `catchup is False`; `max_active_runs == 1`; existe `ingest_inaturalist` sin dependencias previas; existe el grupo `dbt_medallion` con una tarea `run` y una `test` para cada uno de `stg_inaturalist__observations`, `int_observations__geospatial_enriched`, `dim_species`, `dim_users`, `dim_date`, `fct_observations`; toda tarea de `dbt_medallion` es descendiente de `ingest_inaturalist`; la tarea `run` de `int_observations__geospatial_enriched` depende de la `test` de staging; la `run` de `fct_observations` depende de las `test` de las tres dimensiones; no existen tareas fuera de `ingest_inaturalist` y `dbt_medallion`
- [X] T018 [P] [US1] Escribir `tests/orchestration/test_ingest_task.py`: con `unittest.mock` sobre `LambdaHook.invoke_lambda`, (a) una respuesta con `StatusCode: 200` y `Payload` `{"statusCode": 200, "body": "Ingested 3 observations"}` hace que `execute()` devuelva el payload; (b) una respuesta que incluye la clave `FunctionError` hace que `execute()` lance `ValueError` (FR-003); además comprobar que la tarea usa `function_name == "birds-inaturalist-ingestion"` e `invocation_type == "RequestResponse"`

### Implementación de la User Story 1

- [X] T019 [US1] Implementar `orchestration/dags/nantes_birds_pipeline.py` con `from airflow.sdk import DAG` (context manager): `dag_id="nantes_birds_pipeline"`, `schedule="0 5 * * *"`, `start_date=datetime(2026, 10, 1, tzinfo=timezone.utc)`, `catchup=False`, `max_active_runs=1`, `tags=["nantes-birds", "elt"]`; tarea `ingest_inaturalist` = `LambdaInvokeFunctionOperator(function_name="birds-inaturalist-ingestion", invocation_type="RequestResponse", payload="{}", log_type="Tail", aws_conn_id="aws_default", botocore_config={"read_timeout": 200, "connect_timeout": 10, "retries": {"max_attempts": 0}})`; grupo `DbtTaskGroup(group_id="dbt_medallion", project_config=ProjectConfig(dbt_project_path=DBT_PROJECT_DIR, manifest_path=f"{DBT_PROJECT_DIR}/target/manifest.json"), profile_config=ProfileConfig(profile_name="birds_pipeline", target_name="prod", profiles_yml_filepath=f"{DBT_PROFILES_DIR}/profiles.yml"), execution_config=ExecutionConfig(dbt_executable_path=DBT_EXECUTABLE_PATH), render_config=RenderConfig(load_method=LoadMode.DBT_MANIFEST, test_behavior=TestBehavior.AFTER_EACH))` leyendo las rutas de las variables de entorno de T013/T015; dependencia `ingest_inaturalist >> dbt_medallion`. Sin tareas de Power BI (FR-016)
- [X] T020 [US1] (Validado en la CI del PR #1 en lugar de en local: 26/26 tests pasan) Generar el manifest en local (`cd dbt_birds && dbt deps && BIRDS_S3_BUCKET=ci-placeholder dbt parse --profiles-dir ../orchestration/config --target ci`) y hacer pasar `pytest tests/orchestration/ -v` (T017, T018)
- [X] T021 [US1] Desplegar el DAG en la EC2 con `orchestration/deploy/deploy.sh` (vía Session Manager) y, con el DAG todavía **pausado**, validarlo con `airflow dags test nantes_birds_pipeline` (se ejecuta sin el scheduler y sin depender de la pausa); comprobar en Athena que `birds_dbt.fct_observations` se actualizó. Si alguna tarea falla con `AccessDenied`, añadir la acción mínima que falte a [contracts/iam-policy.md](contracts/iam-policy.md) y a `infra/airflow/iam.tf` (sin comodines), aplicar y repetir
- [X] T022 [US1] Pasar a producción **en un mismo paso** (FR-012, SC-005), solo después de que T021 termine en `success`: `aws events disable-rule --name birds-ingestion-daily --region eu-west-3` y a continuación `airflow dags unpause nantes_birds_pipeline`; verificar con `aws events describe-rule --name birds-ingestion-daily --query State` → `"DISABLED"` y `airflow dags list` → no pausado; la regla y el permiso de invocación se conservan para poder revertir

**Punto de control**: User Story 1 funcional — el pipeline completo se ejecuta cada día desde Airflow sin intervención manual

---

## Phase 4: User Story 2 — Contención de Fallos, Reintentos y Alertas (Prioridad: P2)

**Objetivo**: Los fallos se reintentan, detienen las etapas dependientes y, si persisten o la ejecución se retrasa, el responsable recibe un email por el topic SNS existente.

**Prueba Independiente**: Escenarios 3 y 7 de `quickstart.md` — provocar un fallo en la ingesta y otro en un test de dbt, y un retraso; verificar reintentos, `upstream_failed` en las dependientes y la llegada de las alertas.

### Tests de la User Story 2

- [X] T023 [P] [US2] Escribir `tests/orchestration/test_alerts.py` según [contracts/alert-message.md](contracts/alert-message.md): `build_failure_message(context)` devuelve un asunto `"[birds-pipeline] FALLO <task_id> (<YYYY-MM-DD>)"` de **máx. 100 caracteres** (truncar el `task_id` si hace falta) y un cuerpo JSON con `type="task_failure"`, `dag_id`, `run_id`, `logical_date`, `task_id`, `try_number`, `error` (**truncado a 1.000 caracteres**), `log_url` y `hint`; `build_deadline_message(...)` devuelve `type="deadline_missed"` y el asunto `"[birds-pipeline] RETRASO nantes_birds_pipeline (<YYYY-MM-DD>)"` sin `task_id` ni `error`; `notify_failure(context)` llama a `SnsHook.publish_to_target` (mock) con `BIRDS_ALERTS_TOPIC_ARN`; si `publish_to_target` lanza una excepción, `notify_failure` la registra y **no** la propaga
- [X] T024 [P] [US2] Ampliar `tests/orchestration/test_dag_integrity.py`: `default_args["retries"] == 2`, `default_args["retry_delay"] == timedelta(minutes=5)`, `default_args["on_failure_callback"]` es `alerts.notify_failure`, y que todas las tareas (incluidas las de Cosmos) heredan `retries == 2`

### Implementación de la User Story 2

- [X] T025 [US2] Implementar `orchestration/plugins/alerts.py`: funciones puras `build_failure_message(context) -> tuple[str, str]` y `build_deadline_message(dag_id, run_id, logical_date) -> tuple[str, str]` con el formato exacto del contrato; `notify_failure(context)` y `notify_deadline(...)` publican con `SnsHook(aws_conn_id="aws_default").publish_to_target(target_arn=os.environ["BIRDS_ALERTS_TOPIC_ARN"], message=..., subject=...)` dentro de `try/except` que solo registra el error; `log_url` tomado de `context["ti"].log_url`; `hint` = `"Abrir la UI con Session Manager (ver docs/airflow-operations.md)"`
- [X] T026 [US2] Actualizar `orchestration/dags/nantes_birds_pipeline.py`: `default_args={"retries": 2, "retry_delay": timedelta(minutes=5), "on_failure_callback": notify_failure}` aplicado a todo el DAG (incluido el `DbtTaskGroup`); hacer pasar T023 y T024
- [X] T027 [US2] Añadir al DAG la Deadline Alert: si la ejecución no ha terminado 2 horas después de su fecha lógica (07:00 UTC), llamar a `notify_deadline`. Verificar en la documentación de Airflow 3.3.2 la API exacta (`DeadlineAlert`, `DeadlineReference.DAGRUN_LOGICAL_DATE`, tipo de callback) y que funcione con LocalExecutor; si no es viable, documentar la limitación en `specs/002-airflow-orchestration/research.md` §7 y dejar la alarma de CloudWatch como único aviso de retraso
- [ ] T028 [US2] Desplegar con `deploy.sh` y ejecutar los Escenarios 3a, 3b y 7 de `quickstart.md`; restaurar la concurrencia de la Lambda y el test modificado al terminar

**Punto de control**: User Story 2 funcional — ningún fallo pasa desapercibido ni promueve datos de etapas posteriores

---

## Phase 5: User Story 3 — Reconstrucción Completa Bajo Demanda (Prioridad: P3)

**Objetivo**: Un disparo manual con `full_refresh=true` reconstruye desde cero los modelos dbt incrementales, sin tocar la ingesta ni el watermark.

**Prueba Independiente**: Escenario 4 de `quickstart.md` — disparar con `{"full_refresh": true}`, verificar `--full-refresh` en los logs de `fct_observations`, que una segunda ejecución espera en cola y que el watermark no se reinicia.

### Tests de la User Story 3

- [X] T029 [P] [US3] Ampliar `tests/orchestration/test_dag_integrity.py`: `dag.params["full_refresh"]` existe, es de tipo **boolean** y vale `False` por defecto; la tarea `ingest_inaturalist` no referencia `full_refresh` en ningún campo; las tareas `run` de `dbt_medallion` tienen `full_refresh` configurado a partir de `params.full_refresh`

### Implementación de la User Story 3

- [X] T030 [US3] Actualizar `orchestration/dags/nantes_birds_pipeline.py`: `params={"full_refresh": Param(False, type="boolean", description="Reconstruye desde cero los modelos dbt incrementales; no afecta a la ingesta ni al watermark")}`, en el `DbtTaskGroup` `operator_args={"full_refresh": "{{ params.full_refresh }}"}`. Verificado en el código de Cosmos: `full_refresh` está en `template_fields` de `DbtRunMixin`, el valor renderizado `"False"` se convierte a booleano con `to_boolean` y los operadores de test lo descartan, así que no hace falta `render_template_as_native_obj`; hacer pasar T029
- [ ] T031 [US3] Desplegar con `deploy.sh` y ejecutar el Escenario 4 de `quickstart.md` (incluida la comprobación de `COUNT(*) = COUNT(DISTINCT observation_id)` en `birds_dbt.fct_observations` y de que el watermark no se reinicia)

**Punto de control**: Las tres historias funcionan de forma independiente

---

## Phase 6: Polish y Aspectos Transversales

**Propósito**: CI, documentación y validaciones transversales (seguridad, programador único, coste)

- [X] T032 [P] Crear `.github/workflows/airflow_ci.yml` (FR-018): disparador `pull_request` con `paths: ["orchestration/**", "dbt_birds/**", "tests/orchestration/**"]`; Python 3.12; `pip install -r orchestration/requirements.txt --constraint https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.12.txt`, `pip install dbt-athena-community -r tests/requirements-dev.txt`; variable de entorno `BIRDS_S3_BUCKET: ci-placeholder` a nivel de job; `cd dbt_birds && dbt deps && dbt parse --profiles-dir ../orchestration/config --target ci`; `pytest tests/orchestration/ -v`; sin secretos de AWS
- [X] T033 [P] Crear `docs/airflow-operations.md`: abrir la UI con el túnel de Session Manager (output `ui_tunnel_command` de Terraform), credenciales de administrador (dónde está el archivo generado en T013), desplegar cambios con `deploy.sh`, disparar una reconstrucción completa (`airflow dags trigger nantes_birds_pipeline --conf '{"full_refresh": true}'`), relanzar una ejecución fallida (*Clear*), re-ingesta histórica manual (borrar `/birds-pipeline/last_successful_run_date`, excepcional), revertir a EventBridge (`aws events enable-rule` + pausar el DAG), y troubleshooting de memoria (swap, plan B t4g.small)
- [X] T034 [P] Actualizar `docs/architecture.md`: en el diagrama 1 sustituir el disparo de EventBridge por la instancia EC2 de Airflow (EventBridge marcado como desactivado), añadir el flujo Airflow → Lambda y Airflow → dbt → Athena y la alerta Airflow → SNS; en el diagrama 2 cambiar el participante `EventBridge` por `Airflow (DAG nantes_birds_pipeline)`; añadir un diagrama del DAG (copiado de [contracts/dag-interface.md](contracts/dag-interface.md)); añadir las filas de `orchestration/` e `infra/airflow/` al inventario de componentes
- [X] T035 [P] Actualizar `docs/infrastructure.md`: nueva sección "Orquestación con Airflow" (Terraform en `infra/airflow/`, rol `birds-airflow-ec2-role` con referencia a `specs/002-airflow-orchestration/contracts/iam-policy.md`, acceso por Session Manager) y marcar la sección de la regla cron de EventBridge como **desactivada desde la feature 002**, con la orden para reactivarla
- [X] T036 [P] Actualizar `README.md`: diagrama de arquitectura con Airflow, fila "Orquestación" en la tabla del stack, `orchestration/` e `infra/airflow/` en la estructura del repositorio, nueva subsección de puesta en marcha que remita a `docs/airflow-operations.md`, y fila de Airflow en la tabla de estado del proyecto
- [ ] T037 Ejecutar los Escenarios 5 (IAM con `simulate-principal-policy`) y 6 (programador único y recuperación tras parada) de `quickstart.md`
- [ ] T038 Registrar los resultados de todos los escenarios ejecutados (T016, T021, T028, T031, T037) en una nueva sección "Feature 002 — Orquestación con Airflow" de `docs/validation-results.md`, con el mismo formato de tabla (escenario, descripción, estado, notas)
- [ ] T039 Tras una semana de ejecuciones diarias, comprobar en AWS Cost Explorer (filtrando por la etiqueta `component = airflow`) que el coste mensual proyectado es ≤ 25 USD (SC-007) y anotarlo en `docs/validation-results.md`

---

## Dependencias y Orden de Ejecución

### Dependencias entre Fases

- **Setup (Phase 1)**: Sin dependencias; T001 (enmienda de la constitución) debe completarse antes que cualquier otra tarea de implementación (FR-017)
- **Foundational (Phase 2)**: Depende de la Phase 1 — bloquea todas las historias
- **User Story 1 (Phase 3)**: Depende de la Phase 2
- **User Story 2 (Phase 4)**: Depende de la Phase 2; modifica el mismo archivo de DAG que US1, así que en la práctica va después de T019
- **User Story 3 (Phase 5)**: Depende de la Phase 2; modifica el mismo archivo de DAG, así que va después de T019
- **Polish (Phase 6)**: T032–T036 pueden empezar cuando exista T019; T037–T039 dependen de todas las historias desplegadas

### Dependencias entre Historias de Usuario

- **US1 (P1)**: Solo depende de Foundational — es el MVP
- **US2 (P2)**: Necesita el DAG de US1 (T019) para añadir reintentos y callbacks; se prueba de forma independiente con fallos provocados
- **US3 (P3)**: Necesita el DAG de US1 (T019) para añadir el parámetro; independiente de US2

### Dentro de Cada Fase

- Phase 2: T006 → T007/T010 en paralelo → T008 → T009; T011, T012, T014, T015 en paralelo; T013 depende de T011, T012 y T014; T016 depende de T008–T014
- US1: T017/T018 en paralelo (deben fallar primero) → T019 → T020 → T021 → T022
- US2: T023/T024 en paralelo → T025 → T026 → T027 → T028
- US3: T029 → T030 → T031

---

## Ejemplos de Ejecución en Paralelo

### Phase 2 — Infraestructura y configuración a la vez

```bash
Task T007: infra/airflow/variables.tf
Task T010: infra/airflow/outputs.tf
Task T011: orchestration/config/airflow.cfg.template
Task T012: orchestration/systemd/*.service
Task T014: orchestration/deploy/deploy.sh
Task T015: tests/orchestration/conftest.py
```

### User Story 1 — Tests antes de la implementación

```bash
Task T017: tests/orchestration/test_dag_integrity.py
Task T018: tests/orchestration/test_ingest_task.py
# Después, secuencial:
Task T019: orchestration/dags/nantes_birds_pipeline.py
```

### Polish — Documentación y CI en paralelo

```bash
Task T032: .github/workflows/airflow_ci.yml
Task T033: docs/airflow-operations.md
Task T034: docs/architecture.md
Task T035: docs/infrastructure.md
Task T036: README.md
```

---

## Estrategia de Implementación

### Primero el MVP (Solo la User Story 1)

1. Completar la Phase 1 (empezando por la enmienda de la constitución, T001)
2. Completar la Phase 2: EC2 con Airflow funcionando (CRÍTICO — bloquea todas las historias)
3. Completar la Phase 3: User Story 1 (T017–T022)
4. **PARAR Y VALIDAR**: el DAG diario termina en `success` y EventBridge está desactivado
5. US1 ya cierra el hueco principal: la transformación dbt corre en producción cada día

### Entrega Incremental

1. Setup + Foundational → Airflow operativo en la EC2
2. US1 → ingesta + dbt encadenados a diario → **demo del MVP**
3. US2 → reintentos, contención de fallos y alertas
4. US3 → reconstrucción completa bajo demanda
5. Polish → CI del DAG, documentación, validación de seguridad y coste

---

## Notas

- Las tareas **[P]** operan sobre archivos distintos sin dependencias entre sí
- La etiqueta **[Story]** permite trazar cada tarea hasta los criterios de aceptación de spec.md
- `ingestion/` y `dbt_birds/` **no se modifican** en esta feature (FR-002)
- El orquestador **nunca** lee ni escribe el watermark de SSM (FR-009, contrato IAM)
- No desactivar EventBridge (T022) hasta que el DAG haya terminado al menos una ejecución completa en `success`
- Ningún secreto en el repositorio: la contraseña de PostgreSQL y la del administrador se generan en la instancia (T013)
- Dos puntos quedan por verificar contra la documentación al implementar: la plantilla de `full_refresh` en Cosmos (T030) y la API de Deadline Alerts en Airflow 3.3.2 (T027)
