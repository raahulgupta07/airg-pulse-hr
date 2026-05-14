output "efs_id" {
  value = aws_efs_file_system.this.id
}

output "efs_arn" {
  value = aws_efs_file_system.this.arn
}

output "access_point_id" {
  value = aws_efs_access_point.pulse.id
}

output "security_group_id" {
  value = aws_security_group.efs.id
}
