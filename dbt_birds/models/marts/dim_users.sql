{{ config(materialized='table', format='parquet', write_compression='snappy') }}

-- Una fila por user_id. El login o el nombre visible pueden cambiar con el tiempo: se toman los
-- de la observación más reciente.
WITH ranked AS (
    SELECT
        user_id,
        user_login,
        user_display_name,
        ROW_NUMBER() OVER (
            PARTITION BY user_id ORDER BY created_at_utc DESC, observation_id DESC
        ) AS _row_num
    FROM {{ ref('int_observations__geospatial_enriched') }}
)

SELECT
    user_id             AS user_key,
    user_id,
    user_login          AS login,
    user_display_name   AS display_name
FROM ranked
WHERE _row_num = 1
