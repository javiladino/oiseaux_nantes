{{ config(materialized='table', format='parquet', write_compression='snappy') }}

SELECT DISTINCT
    user_id     AS user_key,
    user_id,
    user_login  AS login,
    user_display_name AS display_name
FROM {{ ref('int_observations__geospatial_enriched') }}
