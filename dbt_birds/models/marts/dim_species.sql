{{ config(materialized='table', format='parquet', write_compression='snappy') }}

SELECT DISTINCT
    taxon_id                AS species_key,
    taxon_id,
    taxon_scientific_name   AS scientific_name,
    taxon_common_name       AS common_name,
    taxon_rank,
    taxon_threatened        AS is_threatened
FROM {{ ref('int_observations__geospatial_enriched') }}
