{#
  Se reconstruye completa en cada ejecución (2026-10-12). La versión incremental con
  insert_overwrite y el filtro observed_on > MAX(date_key) borraba las filas anteriores del
  mes en curso (insert_overwrite reemplaza particiones completas) y nunca recogía las
  observaciones subidas con retraso.
#}
{{
    config(
        materialized='table',
        partitioned_by=['year', 'month'],
        format='parquet',
        write_compression='snappy'
    )
}}

WITH int_obs AS (
    SELECT * FROM {{ ref('int_observations__geospatial_enriched') }}
),

dim_species AS (SELECT * FROM {{ ref('dim_species') }}),
dim_users   AS (SELECT * FROM {{ ref('dim_users') }}),
dim_date    AS (SELECT * FROM {{ ref('dim_date') }})

SELECT
    o.observation_id,
    s.species_key,
    u.user_key,
    d.date_key,
    o.latitude,
    o.longitude,
    o.positional_accuracy_m,
    o.quality_grade,
    o.is_research_grade,
    o.observation_period,
    o.created_at_utc,
    o.observed_year   AS year,
    o.observed_month  AS month
FROM int_obs o
JOIN dim_species s ON o.taxon_id = s.species_key
JOIN dim_users   u ON o.user_id  = u.user_key
JOIN dim_date    d ON o.observed_on = d.date_key
