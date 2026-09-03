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

IMPORTANT: the CDK Provider framework only exposes attributes returned
under a top-level ``Data`` key (see ``createResponseEvent``/``submitResponse``
in ``aws-cdk-lib``'s provider-framework runtime) to CloudFormation's
``Fn::GetAtt``. Returning the attribute at the top level of the response
(e.g. ``{"ReplicaCount": "1"}``) is silently accepted by the framework but
never reaches CloudFormation, causing
``Vendor response doesn't contain ReplicaCount attribute`` at deploy time
when the stack later tries ``custom_resource.get_att("ReplicaCount")``.
"""

from typing import Any, Dict

import boto3

PARAMETER_NAME = "/platform/account/env"


def on_event(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Resolve the ingress-nginx replica count from the environment SSM parameter.

    Args:
        event: The Custom Resource lifecycle event dict passed by the CDK
            Provider framework. Unused by this pure mapping logic beyond
            triggering the invocation, except to short-circuit on ``Delete``.
        context: The Lambda context object. Unused.

    Returns:
        A dict with a single key ``Data``, itself a dict with a single key
        ``ReplicaCount`` mapped to ``"1"`` (development) or ``"2"``
        (staging/production). The Provider framework only forwards
        attributes nested under ``Data`` to CloudFormation's
        ``Fn::GetAtt`` - returning ``ReplicaCount`` at the top level would
        be silently dropped. Returns ``{"Data": {}}`` on ``Delete`` without
        reading SSM.

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
        return {"Data": {}}

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

    return {"Data": {"ReplicaCount": replica_count}}
