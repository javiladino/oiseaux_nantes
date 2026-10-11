# Guía de Configuración de Power BI — Pipeline de Aves de Nantes

## Requisitos Previos

- Power BI Desktop (última versión)
- Driver ODBC de Amazon Athena de 64 bits (Simba): descargar desde la consola de AWS Athena o desde [Amazon S3](https://docs.aws.amazon.com/athena/latest/ug/connect-with-odbc.html)
- Credenciales de AWS con `athena:StartQueryExecution`, `athena:GetQueryResults`, `s3:GetObject`, `s3:PutObject` sobre el bucket de staging

---

## Paso 1: Instalar el Driver ODBC de Athena

1. Descargar el instalador del Simba Amazon Athena ODBC Driver de 64 bits.
2. Ejecutar el instalador y aceptar los valores por defecto.
3. Abrir **ODBC Data Source Administrator (64-bit)** en Windows.
4. Hacer clic en **System DSN → Add → Simba Amazon Athena ODBC Driver**.
5. Configurar:
   - **Data Source Name**: `AthenaNantesBirds`
   - **AWS Region**: `eu-west-3`
   - **S3 Output Location**: `s3://<your-bucket>/athena-results/`
   - **Authentication Type**: `IAM Credentials` (o `Default Credentials` para SSO)
   - **Schema**: `birds_dbt`
6. Hacer clic en **Test** para verificar la conectividad y luego en **OK**.

---

## Paso 2: Conectar Power BI Desktop

1. Abrir Power BI Desktop.
2. **Home → Get Data → ODBC**.
3. Seleccionar el DSN `AthenaNantesBirds` en el desplegable.
4. Hacer clic en **OK**.
5. En el Navigator, desplegar `birds_dbt` y seleccionar las cuatro tablas de marts:
   - `fct_observations`
   - `dim_species`
   - `dim_users`
   - `dim_date`
6. Elegir el modo **Import** (no DirectQuery).
7. Hacer clic en **Load**.

---

## Paso 3: Configurar las Relaciones (Vista Model)

Cambiar a la **Model view** de Power BI y crear las siguientes relaciones:

| Tabla origen | Columna origen | Tabla destino | Columna destino | Cardinalidad |
|--------------|----------------|---------------|-----------------|--------------|
| `fct_observations` | `species_key` | `dim_species` | `species_key` | Many-to-One |
| `fct_observations` | `user_key` | `dim_users` | `user_key` | Many-to-One |
| `fct_observations` | `date_key` | `dim_date` | `date_key` | Many-to-One |

---

## Paso 4: Construir los Tres Visuales Requeridos

### 4a. Mapa Geoespacial (FR-013)
- Tipo de visual: **Map** o **ArcGIS Maps for Power BI**
- Latitud: `fct_observations[latitude]`
- Longitud: `fct_observations[longitude]`
- Tooltip: `dim_species[common_name]`, `fct_observations[quality_grade]`
- Añadir un **Slicer** sobre `dim_species[common_name]`

### 4b. Gráfico de Barras de Tendencia Estacional
- Tipo de visual: **Clustered Bar Chart**
- Eje X: `dim_date[month_name]`
- Eje Y: `COUNT(fct_observations[observation_id])`
- Leyenda: `dim_date[biological_season]` (Primavera / Verano / Otoño / Invierno)
- Añadir un **Date Range Slicer** sobre `dim_date[date_key]`

### 4c. Tabla de Ranking + Medidas DAX (FR-012)

Añadir estas medidas a `fct_observations`:

```dax
Total Observations = COUNTROWS(fct_observations)

Distinct Species = DISTINCTCOUNT(fct_observations[species_key])

Research Grade % =
    DIVIDE(
        CALCULATE(COUNTROWS(fct_observations), fct_observations[is_research_grade] = TRUE()),
        COUNTROWS(fct_observations)
    )
```

Columnas del visual de tabla:
- `dim_species[common_name]` + `COUNT(fct_observations[observation_id])` ordenado DESC
- `dim_users[login]` + `COUNT(fct_observations[observation_id])` ordenado DESC

---

## Paso 5: Publicar en Power BI Service

1. **Home → Publish** → seleccionar el workspace.
2. En Power BI Service, ir a la configuración del dataset.
3. En **Scheduled Refresh**, configurar:
   - Frecuencia: **Diaria**
   - Hora: programarla **después** del disparo cron de EventBridge sobre Lambda (ver `docs/infrastructure.md`)
   - Credenciales: introducir las credenciales de AWS de la conexión ODBC

---

## Checklist de Verificación

- [ ] El mapa muestra las observaciones geolocalizadas dentro del límite de Nantes
- [ ] El gráfico estacional muestra los recuentos mensuales con los 4 colores de estación biológica
- [ ] La tabla de ranking lista las especies y los observadores principales
- [ ] El filtrado cruzado funciona entre los tres visuales
- [ ] Tras re-ejecutar el pipeline y actualizar el dataset, las observaciones nuevas aparecen sin intervención manual
