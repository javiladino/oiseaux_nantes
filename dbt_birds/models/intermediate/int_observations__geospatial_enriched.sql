{{ config(materialized='view') }}

WITH stg AS (
    SELECT * FROM {{ ref('stg_inaturalist__observations') }}
),

bbox_filtered AS (
    SELECT *
    FROM stg
    WHERE
        latitude  >= 46.8600781 AND latitude  <= 47.8359431
        AND longitude >= -2.6257395 AND longitude <= -0.9466615
        -- Sin fecha de observación no hay date_key en el modelo estrella; staging las conserva
        -- y su test not_null de observed_on avisa (warn) de cuántas hay.
        AND observed_on IS NOT NULL
),

enriched AS (
    SELECT
        observation_id,
        created_at_utc,
        observed_on,
        latitude,
        longitude,
        positional_accuracy_m,
        quality_grade,
        (quality_grade = 'research')                                            AS is_research_grade,
        CASE
            WHEN HOUR(AT_TIMEZONE(created_at_utc, 'Europe/Paris')) BETWEEN 0  AND 5  THEN 'Madrugada'
            WHEN HOUR(AT_TIMEZONE(created_at_utc, 'Europe/Paris')) BETWEEN 6  AND 11 THEN 'Mañana'
            WHEN HOUR(AT_TIMEZONE(created_at_utc, 'Europe/Paris')) BETWEEN 12 AND 17 THEN 'Tarde'
            ELSE 'Noche'
        END                                                                     AS observation_period,
        taxon_id,
        taxon_scientific_name,
        taxon_common_name,
        taxon_rank,
        taxon_threatened,
        user_id,
        user_login,
        user_display_name,
        YEAR(observed_on)                                                       AS observed_year,
        MONTH(observed_on)                                                      AS observed_month
    FROM bbox_filtered
)

SELECT * FROM enriched
