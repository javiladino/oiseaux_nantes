{{ config(materialized='table', format='parquet', write_compression='snappy') }}

-- Una fila por taxon_id. Los atributos del taxón (nombre común, estado de amenaza...) pueden
-- variar entre observaciones descargadas en momentos distintos: se toman los de la observación
-- más reciente.
WITH ranked AS (
    SELECT
        taxon_id,
        taxon_scientific_name,
        taxon_common_name,
        taxon_rank,
        taxon_threatened,
        ROW_NUMBER() OVER (
            PARTITION BY taxon_id ORDER BY created_at_utc DESC, observation_id DESC
        ) AS _row_num
    FROM {{ ref('int_observations__geospatial_enriched') }}
)

SELECT
    taxon_id                AS species_key,
    taxon_id,
    taxon_scientific_name   AS scientific_name,
    taxon_common_name       AS common_name,
    taxon_rank,
    taxon_threatened        AS is_threatened
FROM ranked
WHERE _row_num = 1
