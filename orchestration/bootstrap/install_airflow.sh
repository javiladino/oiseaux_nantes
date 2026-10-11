#!/usr/bin/env bash
# Bootstrap de la EC2 de Airflow (user_data). Plantilla de Terraform `templatefile`:
# las variables de Terraform son bucket_name, alerts_topic_arn, repo_url, repo_branch y region
# (interpoladas con la sintaxis de templatefile); las variables de bash se escriben siempre
# como $VAR, sin llaves, para no colisionar con esa sintaxis.
# Idempotente: puede re-ejecutarse sin romper una instalación existente.
set -euo pipefail
exec > >(tee -a /var/log/airflow-bootstrap.log) 2>&1

BUCKET_NAME="${bucket_name}"
ALERTS_TOPIC_ARN="${alerts_topic_arn}"
REPO_URL="${repo_url}"
REPO_BRANCH="${repo_branch}"
AWS_REGION="${region}"

AIRFLOW_VERSION="3.3.2"
PYTHON_VERSION="3.12"
CONSTRAINTS_URL="https://raw.githubusercontent.com/apache/airflow/constraints-$AIRFLOW_VERSION/constraints-$PYTHON_VERSION.txt"
REPO_DIR=/opt/oiseaux_nantes
AIRFLOW_HOME=/opt/airflow
ENV_FILE=/etc/airflow/airflow.env

echo "== (1) Swap de 2 GB =="
if [[ ! -f /swapfile ]]; then
  dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

echo "== (2) Paquetes del sistema =="
dnf install -y python3.12 python3.12-pip git postgresql16-server gettext

echo "== (3) PostgreSQL =="
if [[ ! -f /var/lib/pgsql/data/PG_VERSION ]]; then
  postgresql-setup --initdb
  # Autenticación por contraseña en localhost (AL2023 usa ident por defecto).
  sed -i -E 's/^(host\s+all\s+all\s+(127\.0\.0\.1\/32|::1\/128)\s+)ident/\1scram-sha-256/' /var/lib/pgsql/data/pg_hba.conf
fi
systemctl enable --now postgresql

mkdir -p /etc/airflow
if [[ -f "$ENV_FILE" ]]; then
  DB_PASSWORD="$(grep '^AIRFLOW_DB_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)"
else
  DB_PASSWORD="$(openssl rand -hex 24)"
fi
if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname = 'airflow'" | grep -q 1; then
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c "ALTER USER airflow WITH PASSWORD '$DB_PASSWORD';"
else
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c "CREATE USER airflow WITH PASSWORD '$DB_PASSWORD';"
fi
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname = 'airflow'" | grep -q 1; then
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c "CREATE DATABASE airflow OWNER airflow;"
fi

echo "== (4) Usuario airflow y repositorio =="
id airflow &>/dev/null || useradd --system --create-home --home-dir /home/airflow --shell /bin/bash airflow
if [[ ! -d "$REPO_DIR/.git" ]]; then
  git clone --branch "$REPO_BRANCH" "$REPO_URL" "$REPO_DIR"
fi
mkdir -p "$AIRFLOW_HOME/logs"
chown -R airflow:airflow "$REPO_DIR" "$AIRFLOW_HOME"

echo "== (5) Virtualenv de Airflow =="
if [[ ! -x /opt/airflow-venv/bin/airflow ]]; then
  "python$PYTHON_VERSION" -m venv /opt/airflow-venv
  /opt/airflow-venv/bin/pip install --upgrade pip
  /opt/airflow-venv/bin/pip install -r "$REPO_DIR/orchestration/requirements.txt" --constraint "$CONSTRAINTS_URL"
fi

echo "== (6) Virtualenv de dbt (separado de Airflow) =="
if [[ ! -x /opt/dbt-venv/bin/dbt ]]; then
  "python$PYTHON_VERSION" -m venv /opt/dbt-venv
  /opt/dbt-venv/bin/pip install --upgrade pip
  /opt/dbt-venv/bin/pip install dbt-athena-community
fi

echo "== (7) Variables de entorno =="
if [[ ! -f "$ENV_FILE" ]]; then
  FERNET_KEY="$(/opt/airflow-venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
  cat > "$ENV_FILE" <<ENV
AIRFLOW_HOME=$AIRFLOW_HOME
AIRFLOW_DB_PASSWORD=$DB_PASSWORD
AIRFLOW__CORE__FERNET_KEY=$FERNET_KEY
AIRFLOW__API_AUTH__JWT_SECRET=$(openssl rand -hex 32)
AIRFLOW__API__SECRET_KEY=$(openssl rand -hex 32)
AIRFLOW_CONN_AWS_DEFAULT=aws://?region_name=$AWS_REGION
AWS_DEFAULT_REGION=$AWS_REGION
BIRDS_S3_BUCKET=$BUCKET_NAME
BIRDS_ALERTS_TOPIC_ARN=$ALERTS_TOPIC_ARN
DBT_PROJECT_DIR=$REPO_DIR/dbt_birds
DBT_PROFILES_DIR=$REPO_DIR/orchestration/config
DBT_EXECUTABLE_PATH=/opt/dbt-venv/bin/dbt
ENV
fi
chown airflow:airflow "$ENV_FILE"
chmod 600 "$ENV_FILE"

echo "== (8) airflow.cfg =="
AIRFLOW_DB_PASSWORD="$DB_PASSWORD" envsubst '$AIRFLOW_DB_PASSWORD' \
  < "$REPO_DIR/orchestration/config/airflow.cfg.template" > "$AIRFLOW_HOME/airflow.cfg"
chown airflow:airflow "$AIRFLOW_HOME/airflow.cfg"
chmod 600 "$AIRFLOW_HOME/airflow.cfg"

run_as_airflow() {
  sudo -u airflow bash -c "set -a; source $ENV_FILE; set +a; $*"
}

echo "== (9) Migración de la base de metadatos =="
run_as_airflow "/opt/airflow-venv/bin/airflow db migrate"

echo "== (10) Despliegue inicial (dbt deps + dbt parse) =="
run_as_airflow "$REPO_DIR/orchestration/deploy/deploy.sh"

echo "== (11) Servicios systemd =="
for svc in airflow-api-server airflow-scheduler airflow-dag-processor; do
  install -m 644 "$REPO_DIR/orchestration/systemd/$svc.service" "/etc/systemd/system/$svc.service"
done
systemctl daemon-reload
systemctl enable --now airflow-api-server airflow-scheduler airflow-dag-processor

echo "== (12) Contraseña del administrador =="
# SimpleAuthManager la genera al arrancar el api-server.
for _ in $(seq 1 30); do
  [[ -f "$AIRFLOW_HOME/simple_auth_manager_passwords.json.generated" ]] && break
  sleep 5
done
if [[ -f "$AIRFLOW_HOME/simple_auth_manager_passwords.json.generated" ]]; then
  chown airflow:airflow "$AIRFLOW_HOME/simple_auth_manager_passwords.json.generated"
  chmod 600 "$AIRFLOW_HOME/simple_auth_manager_passwords.json.generated"
fi

echo "== Bootstrap de Airflow completado =="
