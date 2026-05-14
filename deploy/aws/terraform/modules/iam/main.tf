data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# --- Task execution role (pulls image, reads secrets/SSM, writes logs) ---

resource "aws_iam_role" "task_execution" {
  name               = "${var.name_prefix}-ecs-task-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "task_execution_managed" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "task_execution_extra" {
  statement {
    sid       = "ReadSecrets"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = length(var.secret_arns) > 0 ? var.secret_arns : ["*"]
  }

  statement {
    sid       = "ReadSsm"
    actions   = ["ssm:GetParameters", "ssm:GetParameter", "ssm:GetParametersByPath"]
    resources = length(var.ssm_param_arns) > 0 ? values(var.ssm_param_arns) : ["*"]
  }

  statement {
    sid       = "DecryptKms"
    actions   = ["kms:Decrypt"]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "task_execution_extra" {
  name   = "${var.name_prefix}-ecs-task-execution-extra"
  policy = data.aws_iam_policy_document.task_execution_extra.json
}

resource "aws_iam_role_policy_attachment" "task_execution_extra" {
  role       = aws_iam_role.task_execution.name
  policy_arn = aws_iam_policy.task_execution_extra.arn
}

# --- Task role (runtime perms inside container) ---

resource "aws_iam_role" "task" {
  name               = "${var.name_prefix}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

data "aws_iam_policy_document" "task_base" {
  statement {
    sid = "Logs"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams",
    ]
    resources = ["${var.log_group_arn}:*", var.log_group_arn]
  }
}

resource "aws_iam_policy" "task_base" {
  name   = "${var.name_prefix}-ecs-task-base"
  policy = data.aws_iam_policy_document.task_base.json
}

resource "aws_iam_role_policy_attachment" "task_base" {
  role       = aws_iam_role.task.name
  policy_arn = aws_iam_policy.task_base.arn
}

# Optional S3 policy
data "aws_iam_policy_document" "task_s3" {
  count = var.s3_bucket_name != "" ? 1 : 0

  statement {
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket",
      "s3:GetObjectAcl",
      "s3:PutObjectAcl",
    ]
    resources = [
      "arn:aws:s3:::${var.s3_bucket_name}",
      "arn:aws:s3:::${var.s3_bucket_name}/*",
    ]
  }
}

resource "aws_iam_policy" "task_s3" {
  count  = var.s3_bucket_name != "" ? 1 : 0
  name   = "${var.name_prefix}-ecs-task-s3"
  policy = data.aws_iam_policy_document.task_s3[0].json
}

resource "aws_iam_role_policy_attachment" "task_s3" {
  count      = var.s3_bucket_name != "" ? 1 : 0
  role       = aws_iam_role.task.name
  policy_arn = aws_iam_policy.task_s3[0].arn
}
