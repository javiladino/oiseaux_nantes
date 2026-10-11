{#
  Crea (si no existe) la tabla externa birds_raw.observations sobre el JSON crudo que escribe
  la Lambda en s3://<bucket>/raw/inaturalist/observations/year=YYYY/month=MM/.

  Usa partition projection: Athena deduce las particiones year/month a partir de la ruta, así
  que las particiones nuevas de cada mes son visibles sin MSCK REPAIR ni registro manual.

  Sustituye a `dbt run-operation stage_external_sources`: el paquete dbt_external_tables no
  tiene implementación para el adaptador de Athena.

  Uso (idempotente; deploy.sh lo ejecuta en cada despliegue):
    dbt run-operation create_raw_observations_table
#}
{% macro create_raw_observations_table() %}
    {%- set location = 's3://' ~ env_var('BIRDS_S3_BUCKET') ~ '/raw/inaturalist/observations/' -%}

    {%- set ddl -%}
CREATE EXTERNAL TABLE IF NOT EXISTS birds_raw.observations (
    id                  bigint,
    created_at          string,
    observed_on         string,
    location            string,
    positional_accuracy int,
    quality_grade       string,
    taxon               struct<id:bigint, name:string, preferred_common_name:string, rank:string, threatened:boolean>,
    `user`              struct<id:bigint, login:string, name:string>
)
PARTITIONED BY (year string, month string)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
WITH SERDEPROPERTIES ('ignore.malformed.json' = 'true')
LOCATION '{{ location }}'
TBLPROPERTIES (
    'projection.enabled'        = 'true',
    'projection.year.type'      = 'integer',
    'projection.year.range'     = '2024,2040',
    'projection.month.type'     = 'integer',
    'projection.month.range'    = '1,12',
    'projection.month.digits'   = '2',
    'storage.location.template' = '{{ location }}year=${year}/month=${month}/'
)
    {%- endset -%}

    {% do run_query(ddl) %}
    {{ log("Tabla birds_raw.observations disponible sobre " ~ location, info=True) }}
{% endmacro %}
