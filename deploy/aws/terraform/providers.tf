provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "pulse"
      Environment = var.env_name
      ManagedBy   = "terraform"
      Component   = "hub-hr-agent"
    }
  }
}
