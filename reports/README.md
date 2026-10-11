# Informes de Power BI

## nantes_birds.pbix

Este directorio contiene el archivo de informe de Power BI del Pipeline de Biodiversidad de Aves en Nantes.

El archivo `.pbix` es un artefacto binario que debe crearse y configurarse con **Power BI Desktop**. Seguir la guía de configuración en [`docs/powerbi-setup.md`](../docs/powerbi-setup.md) para:

1. Conectarse a Athena mediante el DSN ODBC (`AthenaNantesBirds`, esquema `birds_dbt`)
2. Importar las cuatro tablas de marts: `fct_observations`, `dim_species`, `dim_users`, `dim_date`
3. Configurar las relaciones del esquema estrella en la vista Model
4. Construir los tres visuales requeridos:
   - Mapa geoespacial (latitud/longitud de `fct_observations`, segmentador de especie)
   - Gráfico de barras de tendencia estacional (recuentos mensuales coloreados por `biological_season`)
   - Tabla de ranking con medidas DAX (`Total Observations`, `Distinct Species`, `Research Grade %`)
5. Guardarlo como `reports/nantes_birds.pbix` y hacer commit del binario
6. Publicarlo en Power BI Service y configurar la actualización programada diaria

### Medidas DAX

```dax
Total Observations = COUNTROWS(fct_observations)

Distinct Species = DISTINCTCOUNT(fct_observations[species_key])

Research Grade % =
    DIVIDE(
        CALCULATE(COUNTROWS(fct_observations), fct_observations[is_research_grade] = TRUE()),
        COUNTROWS(fct_observations)
    )
```

### Relaciones del Esquema Estrella

| Desde | Columna | Hacia | Columna | Cardinalidad |
|-------|---------|-------|---------|--------------|
| fct_observations | species_key | dim_species | species_key | Many-to-One |
| fct_observations | user_key | dim_users | user_key | Many-to-One |
| fct_observations | date_key | dim_date | date_key | Many-to-One |
