# Power BI Setup Guide — Nantes Birds Pipeline

## Prerequisites

- Power BI Desktop (latest)
- Amazon Athena ODBC Driver 64-bit (Simba): download from the AWS Athena console or [Amazon S3](https://docs.aws.amazon.com/athena/latest/ug/connect-with-odbc.html)
- AWS credentials with `athena:StartQueryExecution`, `athena:GetQueryResults`, `s3:GetObject`, `s3:PutObject` on the staging bucket

---

## Step 1: Install the Athena ODBC Driver

1. Download the 64-bit Simba Amazon Athena ODBC Driver installer.
2. Run the installer and accept defaults.
3. Open **ODBC Data Source Administrator (64-bit)** from Windows.
4. Click **System DSN → Add → Simba Amazon Athena ODBC Driver**.
5. Configure:
   - **Data Source Name**: `AthenaNantesBirds`
   - **AWS Region**: `eu-west-3`
   - **S3 Output Location**: `s3://<your-bucket>/athena-results/`
   - **Authentication Type**: `IAM Credentials` (or `Default Credentials` for SSO)
   - **Schema**: `birds_dbt`
6. Click **Test** to verify connectivity, then **OK**.

---

## Step 2: Connect Power BI Desktop

1. Open Power BI Desktop.
2. **Home → Get Data → ODBC**.
3. Select the DSN `AthenaNantesBirds` from the dropdown.
4. Click **OK**.
5. In the Navigator, expand `birds_dbt` and select all four mart tables:
   - `fct_observations`
   - `dim_species`
   - `dim_users`
   - `dim_date`
6. Choose **Import** mode (not DirectQuery).
7. Click **Load**.

---

## Step 3: Configure Relationships (Model View)

Switch to **Model view** in Power BI and create the following relationships:

| From table | From column | To table | To column | Cardinality |
|-----------|-------------|----------|-----------|-------------|
| `fct_observations` | `species_key` | `dim_species` | `species_key` | Many-to-One |
| `fct_observations` | `user_key` | `dim_users` | `user_key` | Many-to-One |
| `fct_observations` | `date_key` | `dim_date` | `date_key` | Many-to-One |

---

## Step 4: Build the Three Required Visuals

### 4a. Geospatial Map (FR-013)
- Visual type: **Map** or **ArcGIS Maps for Power BI**
- Latitude: `fct_observations[latitude]`
- Longitude: `fct_observations[longitude]`
- Tooltip: `dim_species[common_name]`, `fct_observations[quality_grade]`
- Add a **Slicer** on `dim_species[common_name]`

### 4b. Seasonal Trend Bar Chart
- Visual type: **Clustered Bar Chart**
- X-axis: `dim_date[month_name]`
- Y-axis: `COUNT(fct_observations[observation_id])`
- Legend: `dim_date[biological_season]` (Primavera / Verano / Otoño / Invierno)
- Add a **Date Range Slicer** on `dim_date[date_key]`

### 4c. Ranking Table + DAX Measures (FR-012)

Add these measures to `fct_observations`:

```dax
Total Observations = COUNTROWS(fct_observations)

Distinct Species = DISTINCTCOUNT(fct_observations[species_key])

Research Grade % =
    DIVIDE(
        CALCULATE(COUNTROWS(fct_observations), fct_observations[is_research_grade] = TRUE()),
        COUNTROWS(fct_observations)
    )
```

Table visual columns:
- `dim_species[common_name]` + `COUNT(fct_observations[observation_id])` sorted DESC
- `dim_users[login]` + `COUNT(fct_observations[observation_id])` sorted DESC

---

## Step 5: Publish to Power BI Service

1. **Home → Publish** → select your workspace.
2. In the Power BI Service, navigate to the dataset settings.
3. Under **Scheduled Refresh**, configure:
   - Frequency: **Daily**
   - Time: set to run **after** the EventBridge Lambda cron trigger (see `docs/infrastructure.md`)
   - Credentials: enter AWS credentials for the ODBC connection

---

## Verification Checklist

- [ ] Map renders geolocated observations within the Nantes boundary
- [ ] Seasonal chart shows monthly counts with 4 biological season colours
- [ ] Ranking table lists top species and top observers
- [ ] Cross-filtering works across all three visuals
- [ ] After pipeline re-run and dataset refresh, new observations appear without manual intervention
