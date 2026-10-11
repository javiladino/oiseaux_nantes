#!/usr/bin/env bash
# Despliega en la EC2 la última versión del repositorio:
#   1. git pull de la rama desplegada
#   2. dbt deps + dbt parse para regenerar dbt_birds/target/manifest.json (LoadMode.DBT_MANIFEST)
# No reinicia servicios: el dag-processor recarga el DAG solo.
#
# Uso (desde una sesión de Session Manager):
#   sudo -u airflow /opt/oiseaux_nantes/orchestration/deploy/deploy.sh
set -euo pipefail

REPO_DIR=/opt/oiseaux_nantes
DBT=/opt/dbt-venv/bin/dbt

if [[ "$(id -un)" != "airflow" ]]; then
  echo "Ejecutar como el usuario airflow: sudo -u airflow $0" >&2
  exit 1
fi

# sources.yml y profiles.yml usan env_var('BIRDS_S3_BUCKET').
set -a
# shellcheck disable=SC1091
source /etc/airflow/airflow.env
set +a

git -C "$REPO_DIR" pull --ff-only

cd "$REPO_DIR/dbt_birds"
"$DBT" deps
"$DBT" parse --profiles-dir "$REPO_DIR/orchestration/config" --target prod

echo "Despliegue completado: $(git -C "$REPO_DIR" rev-parse --short HEAD)"
