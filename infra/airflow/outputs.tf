output "instance_id" {
  description = "ID de la instancia de Airflow."
  value       = aws_instance.airflow.id
}

output "role_arn" {
  description = "ARN del rol de la instancia (para simulate-principal-policy)."
  value       = aws_iam_role.airflow.arn
}

output "security_group_id" {
  description = "Security group de la instancia (sin reglas de entrada)."
  value       = aws_security_group.airflow.id
}

output "ui_tunnel_command" {
  description = "Abre un túnel local al puerto 8080 de Airflow; después visitar http://localhost:8080."
  value       = "aws ssm start-session --region ${var.region} --target ${aws_instance.airflow.id} --document-name AWS-StartPortForwardingSession --parameters '{\"portNumber\":[\"8080\"],\"localPortNumber\":[\"8080\"]}'"
}
