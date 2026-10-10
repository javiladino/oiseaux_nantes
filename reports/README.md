# Power BI Reports

## nantes_birds.pbix

This directory holds the Power BI report file for the Nantes Birds Biodiversity Pipeline.

The `.pbix` file is a binary artifact that must be created and configured using **Power BI Desktop**. Follow the setup guide at [`docs/powerbi-setup.md`](../docs/powerbi-setup.md) to:

1. Connect to Athena via ODBC DSN (`AthenaNantesBirds`, schema `birds_dbt`)
2. Import the four mart tables: `fct_observations`, `dim_species`, `dim_users`, `dim_date`
3. Configure star schema relationships in Model view
4. Build the three required visuals:
   - Geospatial map (latitude/longitude from `fct_observations`, species filter slicer)
   - Seasonal trend bar chart (monthly counts coloured by `biological_season`)
   - Ranking table with DAX measures (`Total Observations`, `Distinct Species`, `Research Grade %`)
5. Save as `reports/nantes_birds.pbix` and commit the binary
6. Publish to Power BI Service and configure daily scheduled refresh

### DAX Measures

```dax
Total Observations = COUNTROWS(fct_observations)

Distinct Species = DISTINCTCOUNT(fct_observations[species_key])

Research Grade % =
    DIVIDE(
        CALCULATE(COUNTROWS(fct_observations), fct_observations[is_research_grade] = TRUE()),
        COUNTROWS(fct_observations)
    )
```

### Star Schema Relationships

| From | Column | To | Column | Cardinality |
|------|--------|-----|--------|-------------|
| fct_observations | species_key | dim_species | species_key | Many-to-One |
| fct_observations | user_key | dim_users | user_key | Many-to-One |
| fct_observations | date_key | dim_date | date_key | Many-to-One |
