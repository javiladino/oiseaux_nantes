{#
  Crea (si no existe) la tabla externa birds_raw.observations sobre el JSON crudo que escribe
  la Lambda en s3://<bucket>/raw/inaturalist/observations/year=YYYY/month=MM/.

  Usa partition projection: Athena deduce las particiones year/month a partir de la ruta, así
  que las particiones nuevas de cada mes son visibles sin MSCK REPAIR ni registro manual.

  Sustituye a `dbt run-operation stage_external_sources`: el paquete dbt_external_tables no
  tiene implementación para el adaptador de Athena.

  Uso (idempotente; deploy.sh lo ejecuta en cada despliegue):
    dbt run-operation create_raw_observations_table

  Si cambian las columnas, la tabla existente no se actualiza sola: recrearla con
    dbt run-operation create_raw_observations_table --args '{recreate: true}'
  DROP TABLE en una tabla externa solo borra el metadato; los JSON de S3 no se tocan.
#}
{% macro create_raw_observations_table(recreate=false) %}
    {%- set location = 's3://' ~ env_var('BIRDS_S3_BUCKET') ~ '/raw/inaturalist/observations/' -%}

    {%- set ddl -%}
CREATE EXTERNAL TABLE IF NOT EXISTS birds_raw.observations (
    id                  bigint,
    created_at          string,
    observed_on         string,
    location            string,
    positional_accuracy int,
    quality_grade       string,
    taxon               struct<
                            id:bigint, name:string, preferred_common_name:string, rank:string,
                            threatened:boolean, wikipedia_url:string,
                            default_photo:struct<medium_url:string, square_url:string, attribution:string, license_code:string>
                        >,
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

    {% if recreate %}
        {% do run_query('DROP TABLE IF EXISTS birds_raw.observations') %}
        {{ log("Tabla birds_raw.observations eliminada (solo metadato) para recrearla", info=True) }}
    {% endif %}
    {% do run_query(ddl) %}
    {{ log("Tabla birds_raw.observations disponible sobre " ~ location, info=True) }}
{% endmacro %}
