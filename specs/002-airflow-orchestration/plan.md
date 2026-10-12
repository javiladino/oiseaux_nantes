# Plan de Implementación: Orquestación del Pipeline con Apache Airflow

**Rama**: `002-airflow-orchestration` | **Fecha**: 2026-10-11 | **Spec**: [spec.md](spec.md)

**Entrada**: Especificación del feature en `/specs/002-airflow-orchestration/spec.md`

## Resumen

Añadir Apache Airflow 3.3 como orquestador del pipeline existente, desplegado en una única
instancia EC2 t3.small en `eu-west-3`. Un DAG diario (`nantes_birds_pipeline`, 05:00 UTC) invoca
la Lambda de ingesta sin cambios y, solo si termina bien, ejecuta los modelos dbt
(staging → intermedia → marts) como tareas individuales mediante Astronomer Cosmos, con los tests
de cada modelo antes de sus dependientes. Los fallos definitivos y los retrasos se notifican por
el topic SNS existente. La regla de EventBridge se desactiva y Power BI mantiene su
actualización por horario. La infraestructura (EC2, IAM, SG) se define en Terraform.

## Contexto Técnico

**Lenguaje/Versión**: Python 3.12 (Airflow, DAG, tests); HCL (Terraform ≥ 1.6); Bash (bootstrap y despliegue)

**Dependencias Principales**:
- `apache-airflow==3.3.2` (con el archivo de constraints oficial) — orquestador
- `apache-airflow-providers-amazon` (versión fijada por las constraints) — `LambdaInvokeFunctionOperator`, `SnsHook`
- `astronomer-cosmos~=1.15` — renderiza el proyecto dbt como tareas de Airflow
- `dbt-athena-community` en un virtualenv separado — ejecución de los modelos
- PostgreSQL 16 (paquete de Amazon Linux 2023) — base de metadatos de Airflow
- Terraform + provider `hashicorp/aws` — infraestructura

**Almacenamiento**:
- PostgreSQL local en la EC2 — metadatos de Airflow (ejecuciones, estados, XCom)
- EBS gp3 20 GB cifrado — sistema, virtualenvs, logs de Airflow
- Sin cambios en S3, Glue, Athena ni SSM (la Lambda sigue gestionando el watermark)

**Pruebas**:
- `pytest tests/orchestration/` — integridad del DAG (`DagBag` sin errores), estructura de
  tareas, dependencias, parámetros, reintentos, callbacks
- `terraform validate` + `terraform plan` — infraestructura
- Escenarios end-to-end de `quickstart.md` contra AWS real

**Plataforma Objetivo**: AWS EC2 (Amazon Linux 2023, t3.small, `eu-west-3`) con systemd

**Tipo de Proyecto**: Capa de orquestación añadida a un pipeline ELT existente

**Objetivos de Rendimiento**:
- Ejecución diaria completa (ingesta + 6 modelos con sus tests) en < 30 min; terminada antes de las 07:00 UTC (SC-001)
- Parseo del DAG < 5 s gracias a `LoadMode.DBT_MANIFEST`
- Uso de memoria en reposo < 1,5 GB en una instancia de 2 GB (+2 GB de swap)

**Restricciones**:
- Coste adicional ≤ 25 USD/mes (SC-007): ~19 USD estimados (t3.small + EBS)
- Sin puertos de entrada en el security group; acceso por Session Manager (FR-015)
- IAM sin ARNs comodín salvo la excepción documentada de Session Manager (FR-014, constitución IV)
- `max_active_runs=1`, `catchup=False` (FR-010, FR-011)
- La Lambda y los modelos dbt de la feature 001 no se modifican
- La reconstrucción completa solo afecta a dbt; nunca toca el watermark (FR-009)

**Escala/Alcance**:
- 1 DAG, ~13 tareas (1 ingesta + 6 modelos × run/test), 1 ejecución programada al día
- 1 instancia, 1 rol IAM, 1 security group

## Constitution Check

*PUERTA: Debe superarse antes de la investigación de la Fase 0. Se vuelve a verificar tras el
diseño de la Fase 1.*

| Principio | Puerta | Estado | Notas |
|-----------|--------|--------|-------|
| I. Separación ELT | Airflow solo orquesta: no extrae, no transforma, no procesa filas | **PASS** | La Lambda sigue haciendo EL y dbt sigue haciendo T en Athena; Power BI sigue leyendo solo marts |
| II. API Ética | Sin cambios en la ingesta; nunca más de una ejecución a la vez | **PASS** | `max_active_runs=1`; EventBridge desactivado (FR-012) para evitar dobles llamadas a iNaturalist |
| III. DQ Cero Fallos | Un test fallido bloquea los modelos dependientes | **PASS** | Cosmos `TestBehavior.AFTER_EACH` (FR-005/006); la CI de dbt se mantiene |
| IV. Mínimo Privilegio y Costes | Rol IAM con ARNs concretos; coste casi nulo | **PASS con excepción justificada** | `AmazonSSMManagedInstanceCore` exige `Resource: "*"` (ver Complexity Tracking); ~19 USD/mes |
| V. Idempotencia y Docs | Reintentos seguros; todo versionado y documentado | **PASS** | La Lambda y `insert_overwrite` son idempotentes; DAG, Terraform y docs en el repo |
| Stack tecnológico | Añadir una herramienta exige enmienda MINOR previa | **PASS condicionado** | La primera tarea de implementación es la enmienda 1.1.0 (FR-017) |

**Sin violaciones no justificadas. Se procede a la Fase 0.**

**Re-verificación tras la Fase 1**: el diseño (data-model, contratos y quickstart) no introduce
nuevas desviaciones. El contrato IAM ([contracts/iam-policy.md](contracts/iam-policy.md))
mantiene todos los recursos con ARN concreto salvo la excepción ya justificada. **PASS.**

## Estructura del Proyecto

### Documentación (este feature)

```text
specs/002-airflow-orchestration/
├── plan.md              # Este archivo
├── research.md          # Salida de la Fase 0
├── data-model.md        # Salida de la Fase 1
├── quickstart.md        # Salida de la Fase 1
├── contracts/           # Salida de la Fase 1
│   ├── dag-interface.md
│   ├── iam-policy.md
│   └── alert-message.md
└── tasks.md             # Salida de la Fase 2 (/speckit-tasks — NO lo crea /speckit-plan)
```

### Código Fuente (raíz del repositorio)

```text
orchestration/                          # Nuevo: capa de orquestación
├── dags/
│   └── nantes_birds_pipeline.py        # DAG: ingesta (Lambda) → DbtTaskGroup (Cosmos)
├── plugins/
│   └── alerts.py                       # on_failure_callback y callback de deadline → SNS
├── config/
│   ├── airflow.cfg.template            # Ajustes: LocalExecutor, paralelismo, PostgreSQL
│   └── profiles.yml                # Perfil dbt de producción (target prod)
├── systemd/
│   ├── airflow-api-server.service
│   ├── airflow-scheduler.service
│   └── airflow-dag-processor.service
├── bootstrap/
│   └── install_airflow.sh              # user_data: Python, PostgreSQL, venvs, swap, systemd
├── deploy/
│   └── deploy.sh                       # git pull + dbt deps + dbt parse
└── requirements.txt                    # airflow + provider amazon + cosmos (con constraints)

infra/
└── airflow/                            # Nuevo: Terraform
    ├── main.tf                         # EC2, EBS, security group
    ├── iam.tf                          # Rol, instance profile, políticas en línea
    ├── variables.tf
    ├── outputs.tf
    └── versions.tf

tests/
└── orchestration/                      # Nuevo
    └── test_dag_integrity.py

.github/workflows/
├── dbt_ci.yml                          # Existente; pasa a validación con dbt parse (sin AWS)
└── airflow_ci.yml                      # Nuevo: validación del DAG en PRs

docs/
├── architecture.md                     # Actualizar: Airflow sustituye a EventBridge
├── infrastructure.md                   # Actualizar: desactivar EventBridge, despliegue de Airflow
└── airflow-operations.md               # Nuevo: acceso, despliegue, backfill, troubleshooting

.specify/memory/constitution.md         # Enmienda 1.1.0

ingestion/, dbt_birds/                  # Sin cambios
```

**Decisión de Estructura**: La orquestación vive en `orchestration/` como directorio hermano de
`ingestion/` y `dbt_birds/`, manteniendo la separación por capas del repositorio. La
infraestructura nueva va en `infra/airflow/` (Terraform). Los tests del DAG se añaden en
`tests/orchestration/` junto a los tests existentes de la ingesta.

## Complexity Tracking

| Violación | Por qué es necesaria | Alternativa más simple descartada porque |
|-----------|----------------------|------------------------------------------|
| Política gestionada `AmazonSSMManagedInstanceCore` con `Resource: "*"` en el rol de la EC2 | El agente de Session Manager necesita `ssmmessages:*` y `ec2messages:*`, que AWS no permite restringir por recurso; es la única forma de acceder sin abrir puertos (FR-015) | Un túnel SSH exige abrir el puerto 22, gestionar claves y depender de una IP fija; un ALB con autenticación cuesta ~18 USD/mes y expone la UI a Internet |
| Nueva herramienta en el stack (Airflow) y nuevo componente de cómputo permanente (EC2) | La transformación dbt no está automatizada en producción y las etapas no dependen entre sí (ver Contexto de la spec) | EventBridge + Lambda encadenadas o Step Functions resolverían la orquestación, pero el usuario eligió Airflow explícitamente como objetivo de aprendizaje del proyecto de referencia |
