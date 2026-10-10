{{ config(materialized='table', format='parquet', write_compression='snappy') }}

WITH date_bounds AS (
    SELECT
        DATE_ADD('day', -30, MIN(observed_on)) AS start_date,
        DATE_ADD('day',  30, MAX(observed_on)) AS end_date
    FROM {{ ref('int_observations__geospatial_enriched') }}
),

date_spine AS (
    SELECT
        DATE_ADD('day', seq, start_date) AS date_key
    FROM date_bounds
    CROSS JOIN UNNEST(SEQUENCE(0, DATE_DIFF('day', start_date, end_date))) AS t(seq)
)

SELECT
    date_key,
    YEAR(date_key)                                                          AS year,
    MONTH(date_key)                                                         AS month,
    DATE_FORMAT(date_key, '%M')                                             AS month_name,
    CAST(CEIL(MONTH(date_key) / 3.0) AS INT)                               AS quarter,
    DAY_OF_WEEK(date_key)                                                   AS day_of_week,
    DATE_FORMAT(date_key, '%W')                                             AS day_name,
    WEEK_OF_YEAR(date_key)                                                  AS week_of_year,
    DAY_OF_WEEK(date_key) IN (6, 7)                                         AS is_weekend,
    CASE
        WHEN MONTH(date_key) IN (3, 4, 5)    THEN 'Primavera'
        WHEN MONTH(date_key) IN (6, 7, 8)    THEN 'Verano'
        WHEN MONTH(date_key) IN (9, 10, 11)  THEN 'Otoño'
        ELSE 'Invierno'
    END                                                                     AS biological_season
FROM date_spine
