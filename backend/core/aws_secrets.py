"""AWS Systems Manager Parameter Store bootstrap.

Loaded from `backend/main.py` startup() when env LOAD_SSM=1. Pulls every
parameter under a given prefix and exports each into os.environ (only if
the var is not already set — env vars in the ECS task definition win).

Failure modes are *all* swallowed silently so local development never
needs to install boto3 or have AWS credentials.
"""
from __future__ import annotations

import os
import logging

logger = logging.getLogger(__name__)


def load_secrets_from_ssm(prefix: str = "/pulse/prod/") -> int:
    """Hydrate os.environ from SSM parameters under `prefix`.

    Returns the number of parameters loaded. Returns 0 silently on any
    error (missing boto3, missing IAM, network failure, etc.) so the
    container can keep booting on whatever local env is provided.
    """
    try:
        import boto3  # noqa: WPS433
        from botocore.exceptions import BotoCoreError, ClientError  # noqa: WPS433
    except ImportError:
        logger.debug("[ssm] boto3 not installed — skipping SSM hydration")
        return 0

    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    try:
        ssm = boto3.client("ssm", region_name=region)
    except Exception as e:
        logger.debug(f"[ssm] client init failed: {e}")
        return 0

    loaded = 0
    try:
        paginator = ssm.get_paginator("get_parameters_by_path")
        for page in paginator.paginate(
            Path=prefix,
            Recursive=True,
            WithDecryption=True,
        ):
            for param in page.get("Parameters", []) or []:
                name = (param.get("Name") or "").rsplit("/", 1)[-1]
                value = param.get("Value")
                if not name or value is None:
                    continue
                # Don't overwrite values already provided by the task def.
                if name in os.environ and os.environ[name]:
                    continue
                os.environ[name] = value
                loaded += 1
        logger.info(f"[ssm] hydrated {loaded} env var(s) from prefix={prefix}")
    except (BotoCoreError, ClientError) as e:
        logger.warning(f"[ssm] fetch failed: {e}")
    except Exception as e:  # last-resort safety net
        logger.warning(f"[ssm] unexpected error: {e}")
    return loaded
