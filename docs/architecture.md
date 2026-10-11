# Cartografía del Sistema — Pipeline de Aves de Nantes

Este documento describe la arquitectura del pipeline con diagramas Mermaid: la vista general de
componentes, el flujo de ingesta, el DAG de orquestación, el linaje de dbt, el modelo
dimensional y la CI.

Desde la feature `002-airflow-orchestration`, Apache Airflow (en una EC2) orquesta la ingesta y
la transformación; la regla de EventBridge queda desactivada.

---

## 1. Vista General de Componentes

```mermaid
flowchart LR
    subgraph EXT["Fuente externa"]
        INAT["API iNaturalist v1<br/>GET /v1/observations<br/>taxon_id=3 · bbox Gran Nantes"]
    end

    subgraph AWS["AWS · eu-west-3"]
        direction LR
        subgraph ORCH["Orquestación · orchestration/ · infra/airflow/"]
            AF["Airflow 3.3 en EC2 t3.small<br/>DAG nantes_birds_pipeline<br/>05:00 UTC · LocalExecutor"]
        end
        EB["EventBridge<br/>birds-ingestion-daily<br/>(DESACTIVADA)"]

        subgraph ING["Ingesta (EL) · ingestion/"]
            LAMBDA["Lambda<br/>birds-inaturalist-ingestion<br/>handler.py"]
        end

        SSM[("SSM Parameter Store<br/>/birds-pipeline/<br/>last_successful_run_date")]

        subgraph LAKE["Data Lake · S3"]
            RAW[("raw/inaturalist/observations/<br/>year=YYYY/month=MM/*.json<br/>NDJSON")]
            PROC[("processed/<br/>Parquet + Snappy")]
            ATHRES[("athena-results/")]
        end

        GLUE["Glue Data Catalog<br/>birds_raw · birds_dbt"]
        ATHENA["Athena<br/>motor SQL serverless"]

        subgraph OBS["Observabilidad"]
            CW["CloudWatch Alarms<br/>Errors ≥ 1 · Duration ≥ 150 s"]
            SNS["SNS<br/>birds-pipeline-alerts"]
        end
    end

    subgraph DBT["Transformación (T) · dbt_birds/"]
        DBTCORE["dbt-core + dbt-athena<br/>staging → intermediate → marts"]
    end

    subgraph BI["Consumo"]
        PBI["Power BI<br/>modo Import · refresh diario 08:00 UTC<br/>reports/nantes_birds.pbix"]
    end

    MAIL(["Email del responsable"])

    AF -->|"1 · invoca (RequestResponse)"| LAMBDA
    AF -->|"2 · dbt run/test por modelo (Cosmos)"| DBTCORE
    AF -.->|"fallo o retraso"| SNS
    EB -.->|"solo para revertir"| LAMBDA
    LAMBDA <-->|"get / put watermark"| SSM
    LAMBDA -->|"HTTPS · ~1 req/s · cursor id_above"| INAT
    LAMBDA -->|"PutObject JSON crudo"| RAW
    LAMBDA -.->|"métricas"| CW
    CW --> SNS --> MAIL

    RAW --- GLUE
    GLUE --- ATHENA
    DBTCORE -->|"SQL"| ATHENA
    ATHENA -->|"lee"| RAW
    ATHENA -->|"escribe modelos"| PROC
    ATHENA --> ATHRES

    PBI -->|"ODBC Simba · DSN AthenaNantesBirds<br/>solo esquema marts"| ATHENA
```

**Separación de responsabilidades (constitución I):** Airflow solo orquesta, Lambda solo extrae
y carga (EL), dbt transforma (T) dentro de Athena y Power BI lee únicamente la capa `marts`.

---

## 2. Flujo de Ingesta Incremental

```mermaid
sequenceDiagram
    autonumber
    participant EB as Airflow (DAG nantes_birds_pipeline)
    participant L as Lambda (handler.py)
    participant SSM as SSM Parameter Store
    participant API as API iNaturalist
    participant S3 as S3 raw/

    EB->>L: Invocación diaria (05:00 UTC)
    L->>SSM: get_watermark()
    alt Primera ejecución
        SSM-->>L: ParameterNotFound → None
    else Ejecución incremental
        SSM-->>L: "YYYY-MM-DDTHH:MM:SS"
    end

    loop Paginación con cursor id_above (per_page=200)
        L->>API: GET /v1/observations (created_d1=watermark, id_above=last_id)
        API-->>L: results[]
        Note over L,API: sleep 1 s entre páginas<br/>backoff exponencial ante 429/500/503 (máx. 3 reintentos)
    end

    alt 0 observaciones nuevas
        L-->>EB: 200 "Ingested 0 observations" (sin escritura, watermark intacto)
    else N observaciones
        L->>S3: write_batch() → year=YYYY/month=MM/{timestamp}.json
        S3-->>L: OK
        L->>SSM: put_watermark(run_ts) (solo tras escribir en S3)
        L-->>EB: 200 "Ingested N observations"
    end

    Note over L,SSM: Ante cualquier fallo, el watermark NO se actualiza →<br/>la siguiente ejecución retoma desde el mismo punto (idempotencia)
```

---

## 2b. DAG de Orquestación (`nantes_birds_pipeline`)

```mermaid
flowchart LR
    I["ingest_inaturalist<br/>Lambda · RequestResponse"] --> STG["stg_inaturalist__observations<br/>run → test"]
    STG --> INT["int_observations__geospatial_enriched<br/>run → test (incluye bbox)"]
    INT --> DS["dim_species<br/>run → test"]
    INT --> DU["dim_users<br/>run → test"]
    INT --> DD["dim_date<br/>run → test"]
    DS --> F["fct_observations<br/>run → test"]
    DU --> F
    DD --> F
```

- Diario a las 05:00 UTC, una sola ejecución activa, sin ejecuciones atrasadas (`catchup=False`).
- Cada tarea se reintenta 2 veces (5 min). Si falla definitivamente, las dependientes quedan en
  `upstream_failed` y se envía un email por SNS.
- Si la ejecución no ha terminado a las 07:00 UTC, se envía una alerta de retraso.
- Parámetro `full_refresh` (disparo manual): reconstruye los modelos dbt; la ingesta no cambia.
- Contrato completo: [specs/002-airflow-orchestration/contracts/dag-interface.md](../specs/002-airflow-orchestration/contracts/dag-interface.md).

---

## 3. Linaje de dbt (Arquitectura Medallón)

```mermaid
flowchart TD
    SRC[("source<br/>raw_inaturalist.observations<br/>tabla externa · JsonSerDe")]

    subgraph STG["Staging · view"]
        STGM["stg_inaturalist__observations<br/>cast · aplanado · dedup por observation_id"]
    end

    subgraph INT["Intermedia · view"]
        INTM["int_observations__geospatial_enriched<br/>filtro bbox · observation_period · is_research_grade"]
    end

    subgraph MARTS["Marts · Parquet + Snappy"]
        DS["dim_species<br/>table"]
        DU["dim_users<br/>table"]
        DD["dim_date<br/>table · ±30 días · biological_season"]
        FCT["fct_observations<br/>incremental · insert_overwrite<br/>partición (year, month)"]
    end

    TBBOX{{"test singular<br/>assert_observations_within_nantes_bbox"}}

    SRC --> STGM --> INTM
    INTM --> DS
    INTM --> DU
    INTM --> DD
    INTM --> FCT
    DS --> FCT
    DU --> FCT
    DD --> FCT
    INTM -.-> TBBOX
```

---

## 4. Modelo Dimensional (Esquema Estrella)

```mermaid
erDiagram
    fct_observations }o--|| dim_species : species_key
    fct_observations }o--|| dim_users : user_key
    fct_observations }o--|| dim_date : date_key

    fct_observations {
        BIGINT observation_id PK
        BIGINT species_key FK
        BIGINT user_key FK
        DATE date_key FK
        DOUBLE latitude
        DOUBLE longitude
        INT positional_accuracy_m
        VARCHAR quality_grade
        BOOLEAN is_research_grade
        VARCHAR observation_period
        TIMESTAMP created_at_utc
        INT year
        INT month
    }
    dim_species {
        BIGINT species_key PK
        BIGINT taxon_id
        VARCHAR scientific_name
        VARCHAR common_name
        VARCHAR taxon_rank
        BOOLEAN is_threatened
    }
    dim_users {
        BIGINT user_key PK
        BIGINT user_id
        VARCHAR login
        VARCHAR display_name
    }
    dim_date {
        DATE date_key PK
        INT year
        INT month
        VARCHAR month_name
        INT quarter
        INT day_of_week
        VARCHAR day_name
        INT week_of_year
        BOOLEAN is_weekend
        VARCHAR biological_season
    }
```

---

## 5. CI y Calidad de Datos

```mermaid
flowchart LR
    DEV["Desarrollador"] -->|"PR que modifica dbt_birds/**"| GH["GitHub"]
    GH --> WF["GitHub Actions<br/>.github/workflows/dbt_ci.yml"]
    WF --> S1["pip install dbt-athena-community"]
    S1 --> S2["profiles.yml desde secrets<br/>DBT_ATHENA_S3_STAGING_DIR<br/>DBT_ATHENA_S3_DATA_DIR"]
    S2 --> S3["dbt compile"]
    S3 --> S4["dbt test --select state:modified+"]
    S4 -->|"todos pasan"| OK(["Merge permitido en main"])
    S4 -->|"algún test falla"| KO(["Workflow fallido · merge bloqueado<br/>(constitución III · SC-004)"])
```

---

## Inventario de Componentes

| Componente | Ubicación en el repo | Responsabilidad |
|------------|----------------------|-----------------|
| `handler.py` | `ingestion/` | Orquesta watermark → fetch → write → watermark |
| `inaturalist_client.py` | `ingestion/` | Cliente HTTP paginado, rate limit y reintentos |
| `s3_writer.py` | `ingestion/` | Escribe NDJSON particionado por año/mes |
| `ssm_watermark.py` | `ingestion/` | Lectura/escritura atómica del watermark |
| Tests unitarios / integración | `tests/` | pytest + moto; test real contra la API |
| Proyecto dbt | `dbt_birds/` | Fuentes, modelos medallón, tests |
| DAG de Airflow | `orchestration/dags/` | Encadena ingesta → dbt con reintentos, alertas y `full_refresh` |
| Alertas de Airflow | `orchestration/plugins/alerts.py` | Mensajes de fallo y retraso hacia SNS |
| Despliegue de Airflow | `orchestration/bootstrap/`, `orchestration/deploy/`, `orchestration/systemd/` | Instalación en la EC2, `git pull` + `dbt parse`, servicios |
| Infraestructura de Airflow | `infra/airflow/` | Terraform: EC2, IAM, security group |
| Tests del DAG | `tests/orchestration/` | Integridad del DAG, tarea de ingesta, alertas |
| CI | `.github/workflows/dbt_ci.yml`, `.github/workflows/airflow_ci.yml` | `dbt compile` + `dbt test`; integridad del DAG en cada PR |
| Infraestructura | `docs/infrastructure.md` | EventBridge (desactivada), CloudWatch, SNS, IAM (vía AWS CLI) |
| Operación de Airflow | `docs/airflow-operations.md` | Acceso, despliegue, ejecuciones manuales, recuperación |
| Power BI | `reports/`, `docs/powerbi-setup.md` | Conexión ODBC, relaciones, visuales y medidas DAX |
