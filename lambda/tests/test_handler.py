"""Unit tests for lambda/handler.py.

Uses moto's ``mock_aws`` to stand up a real (mocked) SSM backend and exercises
the actual boto3 ``put_parameter`` / ``get_parameter`` call path, rather than
hand-mocking the boto3 client. Covers every branch of ``on_event`` to reach
100% line coverage of ``handler.py``:

- development            -> {"ReplicaCount": "1"}
- staging                -> {"ReplicaCount": "2"}
- production             -> {"ReplicaCount": "2"}
- parameter missing      -> ParameterNotFound propagates
- unexpected value       -> ValueError raised
- Delete request type    -> short-circuits to {} without reading SSM
"""

import boto3
import pytest
from moto import mock_aws

from handler import PARAMETER_NAME, on_event

REGION = "eu-central-1"


def _put_env(value: str) -> None:
    """Create/overwrite the /platform/account/env parameter under mock_aws."""
    ssm = boto3.client("ssm", region_name=REGION)
    ssm.put_parameter(
        Name=PARAMETER_NAME,
        Value=value,
        Type="String",
        Overwrite=True,
    )


@mock_aws
def test_development_returns_replica_count_1():
    _put_env("development")
    assert on_event({}, None) == {"ReplicaCount": "1"}


@mock_aws
def test_staging_returns_replica_count_2():
    _put_env("staging")
    assert on_event({}, None) == {"ReplicaCount": "2"}


@mock_aws
def test_production_returns_replica_count_2():
    _put_env("production")
    assert on_event({}, None) == {"ReplicaCount": "2"}


@mock_aws
def test_missing_parameter_raises_parameter_not_found():
    ssm = boto3.client("ssm", region_name=REGION)
    with pytest.raises(ssm.exceptions.ParameterNotFound):
        on_event({}, None)


@mock_aws
def test_unexpected_value_raises_value_error():
    _put_env("qa")
    with pytest.raises(ValueError) as exc_info:
        on_event({}, None)
    assert "qa" in str(exc_info.value)


@mock_aws
def test_delete_request_short_circuits_without_reading_ssm():
    # No parameter is created here: if on_event attempted to read SSM on
    # Delete, this would raise ParameterNotFound instead of returning {}.
    assert on_event({"RequestType": "Delete"}, None) == {}
