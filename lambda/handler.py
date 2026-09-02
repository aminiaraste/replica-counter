"""Lambda handler for the ingress-nginx replica-count Custom Resource.

Reads the account environment name from the SSM parameter
``/platform/account/env`` and maps it to the number of ingress-nginx
controller replicas to run, returned as the Custom Resource attribute
``ReplicaCount`` (always a string, per the CloudFormation GetAtt contract).

Mapping:
    development            -> "1"
    staging | production   -> "2"

The parameter is read with no ``try``/``except`` wrapper: if it is missing,
``ssm.exceptions.ParameterNotFound`` propagates uncaught and the Provider
framework marks the Custom Resource operation as FAILED. Any unexpected
value raises ``ValueError`` rather than silently defaulting.
"""

from typing import Any, Dict

import boto3

PARAMETER_NAME = "/platform/account/env"


def on_event(event: Dict[str, Any], context: Any) -> Dict[str, str]:
    """Resolve the ingress-nginx replica count from the environment SSM parameter.

    Args:
        event: The Custom Resource lifecycle event dict passed by the CDK
            Provider framework. Unused by this pure mapping logic beyond
            triggering the invocation, except to short-circuit on ``Delete``.
        context: The Lambda context object. Unused.

    Returns:
        A dict with a single key ``ReplicaCount`` mapped to ``"1"`` (development)
        or ``"2"`` (staging/production). Returns an empty dict on ``Delete``
        without reading SSM.

    Raises:
        botocore.exceptions.ClientError: Propagated uncaught if the SSM
            parameter does not exist (``ParameterNotFound``) or access is denied.
        ValueError: If the parameter value is not one of the expected
            environment names.
    """
    # Nothing to compute on delete, and the SSM parameter may already be
    # gone by the time CloudFormation tears down the Custom Resource
    # (dependency order means the parameter is deleted after this resource
    # on a full stack teardown, but skipping the read here avoids coupling
    # deletion success to the parameter's existence either way).
    if event.get("RequestType") == "Delete":
        return {}

    ssm = boto3.client("ssm")

    # No try/except: ParameterNotFound MUST propagate uncaught.
    response = ssm.get_parameter(Name=PARAMETER_NAME)
    env_value = response["Parameter"]["Value"]

    if env_value == "development":
        replica_count = "1"
    elif env_value in ("staging", "production"):
        replica_count = "2"
    else:
        raise ValueError(f"Unexpected environment value: {env_value}")

    return {"ReplicaCount": replica_count}
