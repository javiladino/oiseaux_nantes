# Guía de Configuración de Power BI — Pipeline de Aves de Nantes

Conexión de Power BI Desktop (Windows) a las tablas de marts en Athena, modelo estrella,
visuales y medidas. Validada el 2026-10-12/13 con el driver Amazon Athena ODBC 2.x.

Power BI solo lee la capa `marts` (constitución I): `fct_observations`, `dim_species`,
`dim_users` y `dim_date`.

---

## Paso 1: Credenciales de solo lectura

No uses las claves del usuario administrador. Crea un usuario IAM dedicado, `oiseaux-powerbi`,
con esta política (sustituye `<account-id>` y `<bucket>`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AthenaListCatalogsNoResourceLevel",
      "Effect": "Allow",
      "Action": "athena:ListDataCatalogs",
      "Resource": "*"
    },
    {
      "Sid": "AthenaQueriesPrimaryWorkgroup",
      "Effect": "Allow",
      "Action": ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults", "athena:StopQueryExecution", "athena:GetWorkGroup"],
      "Resource": "arn:aws:athena:eu-west-3:<account-id>:workgroup/primary"
    },
    {
      "Sid": "AthenaCatalogMetadata",
      "Effect": "Allow",
      "Action": ["athena:GetDataCatalog", "athena:ListDatabases", "athena:GetDatabase", "athena:ListTableMetadata", "athena:GetTableMetadata"],
      "Resource": "arn:aws:athena:eu-west-3:<account-id>:datacatalog/AwsDataCatalog"
    },
    {
      "Sid": "GlueReadMarts",
      "Effect": "Allow",
      "Action": ["glue:GetDatabase", "glue:GetDatabases", "glue:GetTable", "glue:GetTables", "glue:GetPartition", "glue:GetPartitions"],
      "Resource": [
        "arn:aws:glue:eu-west-3:<account-id>:catalog",
        "arn:aws:glue:eu-west-3:<account-id>:database/default",
        "arn:aws:glue:eu-west-3:<account-id>:database/birds_dbt",
        "arn:aws:glue:eu-west-3:<account-id>:table/birds_dbt/*"
      ]
    },
    {
      "Sid": "S3ListBucket",
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::<bucket>"
    },
    {
      "Sid": "S3ReadMarts",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::<bucket>/processed/*"
    },
    {
      "Sid": "S3QueryResults",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload"],
      "Resource": "arn:aws:s3:::<bucket>/athena-results/powerbi/*"
    }
  ]
}
```

```bash
aws iam create-user --user-name oiseaux-powerbi
aws iam put-user-policy --user-name oiseaux-powerbi --policy-name powerbi-readonly-marts \
  --policy-document file://powerbi-readonly-policy.json
aws iam create-access-key --user-name oiseaux-powerbi \
  --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text
```

- `athena:ListDataCatalogs` solo admite `"Resource": "*"` (AWS no permite restringirla por
  recurso). Es una acción de listado que devuelve nombres de catálogos, sin datos.
- **Sin acceso a `birds_raw`**: por eso las vistas `stg_*` e `int_*` de `birds_dbt` no se
  pueden cargar en Power BI (ver Paso 3).
- Borra las claves (`aws iam delete-access-key`) si el equipo Windows no es tuyo.

---

## Paso 2: Driver ODBC y DSN

1. Instala **Amazon Athena ODBC 2.x** de 64 bits:
   https://docs.aws.amazon.com/athena/latest/ug/odbc-v2-driver.html
2. Abre **Orígenes de datos ODBC (64 bits)** con **clic derecho → Ejecutar como administrador**
   (sin permisos de administrador los DSN de sistema pueden no guardarse).
3. **DSN de sistema → Agregar → Amazon Athena ODBC (x64)**:

| Campo | Valor |
|---|---|
| Data source name | `AthenaNantesBirds` |
| Region | `eu-west-3` |
| Catalog | `AwsDataCatalog` |
| Database | `birds_dbt` |
| Workgroup | `primary` |
| S3 output location | `s3://<bucket>/athena-results/powerbi/` |
| Authentication | **IAM Credentials**: User = Access Key ID, Password = Secret Access Key |

4. **Test** → **OK** en el formulario → **Aceptar** en la ventana principal.
5. Vuelve a abrir **Configurar** y comprueba que la región sigue guardada.

---

## Paso 3: Cargar las 4 tablas de marts

1. Power BI Desktop → **Obtener datos → ODBC** → DSN `AthenaNantesBirds`.
2. Credenciales: **Predeterminado o personalizado** (usa las del DSN).
3. En el navegador, `AwsDataCatalog → birds_dbt`, marca **solo**:
   `fct_observations`, `dim_species`, `dim_users`, `dim_date`.
4. **Cargar** (modo Importar).

No marques `stg_inaturalist__observations` ni `int_observations__geospatial_enriched`: son
vistas sobre la tabla raw, a la que este usuario no tiene acceso, y su fallo cancela la carga de
todas las tablas.

---

## Paso 4: Relaciones (vista de modelo)

**Inicio → Administrar relaciones**: deja exactamente estas tres y elimina cualquier otra
creada automáticamente (p. ej. por `year`):

| De (varios) | Columna | A (uno) | Columna |
|---|---|---|---|
| `fct_observations` | `species_key` | `dim_species` | `species_key` |
| `fct_observations` | `user_key` | `dim_users` | `user_key` |
| `fct_observations` | `date_key` | `dim_date` | `date_key` |

Cardinalidad *Varios a uno*, dirección del filtro *Único*, relación activa.

---

## Paso 5: Preparar columnas (vista de tabla)

| Tabla | Columna | Acción |
|---|---|---|
| `dim_date` | `month_name` | **Ordenar por columna → `month`** |
| `dim_date` | nueva columna `season_order` | `SWITCH(dim_date[biological_season], "Invierno", 1, "Primavera", 2, "Verano", 3, "Otoño", 4)`; después `biological_season` → **Ordenar por columna → `season_order`** |
| `dim_date` | `date_key` | Tipo de datos **Fecha** |
| `fct_observations` | `latitude` / `longitude` | **Categoría de datos → Latitud / Longitud**, tipo número decimal |
| `dim_species` | `photo_url` | **Categoría de datos → URL de imagen** |
| `dim_species` | `wikipedia_url` | **Categoría de datos → URL web** |

---

## Paso 6: Medidas DAX (en `fct_observations`)

```dax
Total observaciones = COUNTROWS ( fct_observations )

Especies distintas = DISTINCTCOUNT ( fct_observations[species_key] )

Observadores = DISTINCTCOUNT ( fct_observations[user_key] )

% grado investigación =
DIVIDE (
    CALCULATE ( [Total observaciones], fct_observations[is_research_grade] = TRUE () ),
    [Total observaciones]
)
```

Formato de `% grado investigación`: porcentaje con 1 decimal.

---

## Paso 7: Visuales

| Visual | Configuración |
|---|---|
| **Tarjetas** (×4) | `Total observaciones`, `Especies distintas`, `Observadores`, `% grado investigación` |
| **Mapa** (Azure Maps) | Latitud `latitude`, Longitud `longitude`, tooltips `dim_species[common_name]` y `quality_grade`; activar **Capa de mapa térmico**. Activar el visual en *Opciones → Seguridad → Usar objetos visuales de Azure Maps*. Alternativa: gráfico de dispersión X = `longitude`, Y = `latitude` |
| **Estacionalidad** | Columnas apiladas: eje X `dim_date[month_name]`, eje Y `Total observaciones`, leyenda `biological_season`; ordenar eje por `month_name` ascendente |
| **Ranking de especies** | Tabla: `common_name`, `scientific_name`, `Total observaciones`, `% grado investigación`; filtro del visual **N superior 15** por `Total observaciones` |
| **Ranking de observadores** | Tabla: `dim_users[login]`, `Total observaciones`; **N superior 10** |
| **Segmentaciones** | `dim_date[year]` (estilo *Entre*), `biological_season`, `quality_grade` |

### Top 3 con fotos

Requiere las columnas `photo_url`, `photo_attribution`, `photo_license` y `wikipedia_url` de
`dim_species` (2026-10-13) y la categoría **URL de imagen** del Paso 5.

1. Visual **Tabla** con, en este orden: `dim_species[photo_url]`, `common_name`,
   `scientific_name`, `Total observaciones`, `% grado investigación`, `photo_attribution`.
2. Filtro del visual sobre `common_name`: **N superior 3** por `Total observaciones`.
3. Formato → **Tamaño de imagen**: alto y ancho ~150 px; ajustar el tamaño de texto.
4. Opcional: `wikipedia_url` como columna para abrir la ficha de la especie.

Con el filtro cruzado, el Top 3 y sus fotos cambian al filtrar por estación, año o calidad.

**Licencias**: cada foto tiene la licencia de su autor; muestra siempre `photo_attribution`.
Para publicar el informe, filtra `photo_license` no vacío (fotos Creative Commons): un valor
nulo significa *todos los derechos reservados*.

---

## Paso 8: Actualizar y publicar

- **Inicio → Actualizar** después de las 05:00 UTC (cuando termina el DAG de Airflow).
- Publicar en Power BI Service requiere una cuenta de trabajo o educativa. La actualización
  programada en el servicio necesita un *on-premises data gateway* en un equipo Windows
  encendido; sin él, actualiza en Desktop y vuelve a publicar.
- Guarda el informe como `reports/nantes_birds.pbix`.

---

## Problemas frecuentes

| Error | Causa | Solución |
|---|---|---|
| Código de sistema **4551**: "Una directiva de Control de aplicaciones bloqueó este archivo" (`athenaodbc.dll`) | Smart App Control de Windows 11 o una política de TI (WDAC/AppLocker) | Equipo personal: desactivar Smart App Control (en muchas versiones no se puede reactivar sin reinstalar). Equipo gestionado: pedir a TI que autorice el driver |
| `Required connection parameter is missing: AwsRegion` | El DSN no guardó los campos | Editar el DSN como administrador y cerrar con **OK**; eliminar un DSN de usuario con el mismo nombre; o pasar `AwsRegion=eu-west-3;…` en *Opciones avanzadas → Cadena de conexión* |
| "No se puede autenticar con las credenciales proporcionadas" | Credenciales de tipo *Base de datos* mal copiadas | Usar **Predeterminado o personalizado**; borrar permisos en *Configuración de origen de datos* |
| `not authorized to perform: athena:ListDataCatalogs` | Falta la sentencia sin recurso de la política | Paso 1 |
| `Failed analyzing stored view … glue:GetDatabase … birds_raw` | Se cargaron las vistas `stg_*`/`int_*` | Cargar solo las 4 tablas de marts (Paso 3); eliminar las consultas sobrantes en *Transformar datos* o empezar un archivo nuevo |
| "Tienes cambios pendientes que no se han aplicado" y falla al aplicar | Quedan consultas de vistas o duplicadas `(2)` en el modelo | Igual que la fila anterior |

## Checklist de Verificación

- [ ] El mapa muestra las observaciones dentro del Gran Nantes
- [ ] La estacionalidad va de enero a diciembre con los 4 colores de estación
- [ ] Los rankings muestran las especies y los observadores principales
- [ ] El Top 3 muestra la foto y la atribución de cada especie
- [ ] El filtrado cruzado funciona entre todos los visuales
- [ ] Tras una ejecución del DAG y **Actualizar**, aparecen las observaciones nuevas
