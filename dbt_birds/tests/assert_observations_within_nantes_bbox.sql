-- Singular test: returns rows that are OUTSIDE the Nantes bounding box.
-- The test passes when this query returns 0 rows (SC-003).
SELECT *
FROM {{ ref('int_observations__geospatial_enriched') }}
WHERE
    latitude  < 46.8600781
    OR latitude  > 47.8359431
    OR longitude < -2.6257395
    OR longitude > -0.9466615
