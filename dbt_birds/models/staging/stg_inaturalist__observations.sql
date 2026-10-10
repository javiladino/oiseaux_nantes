{{ config(materialized='view') }}

WITH raw AS (
    SELECT *
    FROM {{ source('raw_inaturalist', 'observations') }}
),

parsed AS (
    SELECT
        CAST(id AS BIGINT)                                          AS observation_id,
        CAST(created_at AS TIMESTAMP)                               AS created_at_utc,
        CAST(observed_on AS DATE)                                   AS observed_on,
        CAST(split_part(location, ',', 1) AS DOUBLE)                AS latitude,
        CAST(split_part(location, ',', 2) AS DOUBLE)                AS longitude,
        CAST(positional_accuracy AS INT)                            AS positional_accuracy_m,
        quality_grade,
        CAST(taxon.id AS BIGINT)                                    AS taxon_id,
        taxon.name                                                  AS taxon_scientific_name,
        taxon.preferred_common_name                                 AS taxon_common_name,
        taxon.rank                                                  AS taxon_rank,
        CAST(taxon.threatened AS BOOLEAN)                           AS taxon_threatened,
        CAST(user.id AS BIGINT)                                     AS user_id,
        user.login                                                  AS user_login,
        user.name                                                   AS user_display_name,
        year                                                        AS _ingested_year,
        month                                                       AS _ingested_month,
        ROW_NUMBER() OVER (
            PARTITION BY id ORDER BY CAST(created_at AS TIMESTAMP) DESC
        )                                                           AS _row_num
    FROM raw
)

SELECT
    observation_id,
    created_at_utc,
    observed_on,
    latitude,
    longitude,
    positional_accuracy_m,
    quality_grade,
    taxon_id,
    taxon_scientific_name,
    taxon_common_name,
    taxon_rank,
    taxon_threatened,
    user_id,
    user_login,
    user_display_name,
    _ingested_year,
    _ingested_month
FROM parsed
WHERE _row_num = 1
