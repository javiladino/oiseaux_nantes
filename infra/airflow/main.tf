data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

# Sin reglas de entrada: la UI solo es accesible con port forwarding de Session Manager (FR-015).
resource "aws_security_group" "airflow" {
  name        = "birds-airflow-sg"
  description = "Airflow EC2: sin entrada; salida HTTPS (APIs de AWS, GitHub, PyPI, repos dnf)"
  vpc_id      = data.aws_vpc.default.id

  egress {
    description = "HTTPS saliente"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "airflow" {
  ami                         = data.aws_ssm_parameter.al2023_ami.value
  instance_type               = var.instance_type
  subnet_id                   = sort(data.aws_subnets.default.ids)[0]
  vpc_security_group_ids      = [aws_security_group.airflow.id]
  iam_instance_profile        = aws_iam_instance_profile.airflow.name
  associate_public_ip_address = true # solo para tráfico saliente; no hay reglas de entrada

  metadata_options {
    http_tokens   = "required" # IMDSv2
    http_endpoint = "enabled"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = var.volume_size_gb
    encrypted   = true
  }

  user_data = templatefile("${path.module}/../../orchestration/bootstrap/install_airflow.sh", {
    bucket_name      = var.bucket_name
    alerts_topic_arn = local.alerts_topic_arn
    repo_url         = var.repo_url
    repo_branch      = var.repo_branch
    region           = var.region
  })

  tags = {
    Name = "birds-airflow"
  }

  lifecycle {
    # Una AMI nueva no debe recrear la instancia (y perder la base de metadatos) en cada plan.
    ignore_changes = [ami, user_data]
  }
}
