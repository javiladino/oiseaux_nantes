# Contrato: Interfaces de los Modelos dbt

**Feature**: `001-nantes-birds-pipeline` | **Fecha**: 2026-10-10

Este documento define la interfaz pública de cada capa de modelos dbt — las columnas en las que
pueden confiar los consumidores posteriores (otros modelos, Power BI). Cualquier cambio en estos
contratos requiere revisión mediante PR.

---

## Contrato Staging → Intermedia

**Productor**: `stg_inaturalist__observations`
**Consumidor**: `int_observations__geospatial_enriched`

El modelo intermedio depende de estas columnas de staging:

| Columna | Tipo | Garantía |
|---------|------|----------|
| `observation_id` | BIGINT | Única, no nula |
| `created_at_utc` | TIMESTAMP | Normalizada a UTC, no nula |
| `observed_on` | DATE | No nula |
| `latitude` | DOUBLE | No nula; valor raw (aún sin filtro bbox) |
| `longitude` | DOUBLE | No nula; valor raw |
| `quality_grade` | VARCHAR | Uno de: `research`, `needs_id`, `casual` |
| `taxon_id` | BIGINT | No nula |
| `taxon_scientific_name` | VARCHAR | No nula |
| `taxon_common_name` | VARCHAR | Admite nulos |
| `taxon_rank` | VARCHAR | No nula |
| `taxon_threatened` | BOOLEAN | No nula |
| `user_id` | BIGINT | No nula |
| `user_login` | VARCHAR | No nula |
| `user_display_name` | VARCHAR | Admite nulos |

---

## Contrato Intermedia → Marts

**Productor**: `int_observations__geospatial_enriched`
**Consumidores**: `fct_observations`, `dim_species`, `dim_users`, `dim_date`

El modelo intermedio garantiza estas columnas a los marts:

| Columna | Tipo | Garantía |
|---------|------|----------|
| `observation_id` | BIGINT | Única, no nula; dentro del bbox de Nantes |
| `created_at_utc` | TIMESTAMP | No nula |
| `observed_on` | DATE | No nula |
| `latitude` | DOUBLE | No nula; `46.86 ≤ lat ≤ 47.84` |
| `longitude` | DOUBLE | No nula; `-2.63 ≤ lng ≤ -0.95` |
| `quality_grade` | VARCHAR | Uno de: `research`, `needs_id`, `casual` |
| `is_research_grade` | BOOLEAN | No nula |
| `observation_period` | VARCHAR | Uno de: `Madrugada`, `Mañana`, `Tarde`, `Noche` |
| `taxon_id` | BIGINT | No nula |
| `taxon_scientific_name` | VARCHAR | No nula |
| `taxon_common_name` | VARCHAR | Admite nulos |
| `taxon_rank` | VARCHAR | No nula |
| `taxon_threatened` | BOOLEAN | No nula |
| `user_id` | BIGINT | No nula |
| `user_login` | VARCHAR | No nula |
| `user_display_name` | VARCHAR | Admite nulos |
| `observed_year` | INT | No nula |
| `observed_month` | INT | No nula |

---

## Contrato Marts → Power BI

**Productor**: capa `marts/`
**Consumidor**: Power BI Desktop / Service (modo Import)

Power BI DEBE referenciar únicamente estas tablas y columnas:

### `fct_observations`

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `observation_id` | BIGINT | PK; identificador único de la observación |
| `species_key` | BIGINT | FK → `dim_species` |
| `user_key` | BIGINT | FK → `dim_users` |
| `date_key` | DATE | FK → `dim_date` |
| `latitude` | DOUBLE | Latitud WGS84 |
| `longitude` | DOUBLE | Longitud WGS84 |
| `quality_grade` | VARCHAR | `research`/`needs_id`/`casual` |
| `is_research_grade` | BOOLEAN | True si es de grado de investigación |
| `observation_period` | VARCHAR | Franja horaria del día |

### `dim_species`

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `species_key` | BIGINT | PK |
| `scientific_name` | VARCHAR | Binomio latino |
| `common_name` | VARCHAR | Nombre en inglés/francés (admite nulos) |
| `taxon_rank` | VARCHAR | Rango taxonómico |
| `is_threatened` | BOOLEAN | Estado de amenaza |

### `dim_users`

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `user_key` | BIGINT | PK |
| `login` | VARCHAR | Nombre de usuario de iNaturalist |
| `display_name` | VARCHAR | Nombre completo (admite nulos) |

### `dim_date`

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `date_key` | DATE | PK |
| `year` | INT | Año natural |
| `month` | INT | Mes (1–12) |
| `month_name` | VARCHAR | Nombre del mes |
| `quarter` | INT | Trimestre (1–4) |
| `day_of_week` | INT | Día ISO (1=lun, 7=dom) |
| `day_name` | VARCHAR | Nombre del día |
| `is_weekend` | BOOLEAN | |
| `biological_season` | VARCHAR | `Primavera`/`Verano`/`Otoño`/`Invierno` |

### Relaciones (Vista Model de Power BI)

```
fct_observations[species_key] → dim_species[species_key]   (Many-to-One)
fct_observations[user_key]    → dim_users[user_key]        (Many-to-One)
fct_observations[date_key]    → dim_date[date_key]         (Many-to-One)
```

### Medidas de Power BI (FR-012)

| Medida | DAX | Descripción |
|--------|-----|-------------|
| Total Observations | `COUNTROWS(fct_observations)` | Recuento de todas las observaciones válidas |
| Distinct Species | `DISTINCTCOUNT(fct_observations[species_key])` | Recuento de especies únicas |
| Research Grade % | `DIVIDE(CALCULATE(COUNTROWS(fct_observations), fct_observations[is_research_grade]), COUNTROWS(fct_observations))` | % de grado de investigación |

---

## Política de Cambios Incompatibles

Cualquier eliminación o renombrado de una columna de este contrato requiere:
1. Un PR con revisión de cumplimiento de la constitución
2. Actualizar el dataset y el informe de Power BI antes del merge
3. Un comentario en el `.yml` del modelo que explique la ruta de migración
