# Requirements Document

## Introduction

**EKS Ingress Replica Config**

This feature delivers a Python CDK project that provisions an EKS cluster, an SSM parameter holding the account environment name, and an `ingress-nginx` Helm chart installation whose replica count is derived at deploy time from that environment value via a Lambda-backed Custom Resource. The work is split into two self-contained top-level folders, `lambda/` and `infrastructure/`, so they can be developed independently. Requirements below are derived from the settled design in `design.md`.

## Glossary

- **ReplicaCount**: The single string attribute (`"1"` or `"2"`) exposed by the Custom Resource, representing the number of `ingress-nginx` controller pod replicas to run for the resolved environment.
- **Custom Resource**: A CloudFormation resource type (`aws_cdk.CustomResource`) backed by a Lambda function, used here to compute `ReplicaCount` at deploy time from the SSM environment parameter.
- **Provider framework**: The `aws_cdk.custom_resources.Provider` construct that wraps a Lambda as an `on_event_handler` and manages CloudFormation custom resource response (PUT) signaling automatically, removing the need for hand-rolled response logic.
- **StringParameter**: An AWS Systems Manager (SSM) Parameter Store resource type that stores a plain-text (non-secret) string value, used here for `/platform/account/env`.
- **Managed node group**: An Amazon EKS-managed group of EC2 worker nodes attached to the cluster, here fixed at a single `t3.medium` instance (min=1, max=1, desired=1).
- **Vendored chart / `chart_asset`**: A Helm chart whose contents are downloaded once (via `helm pull --untar`) and committed as plain files into the repository at `infrastructure/charts/ingress-nginx/`, rather than fetched live from a remote Helm repository at deploy time. It is installed via the `chart_asset` property (an `aws_cdk.aws_s3_assets.Asset` pointing at that local directory), which CDK zips and uploads to the CDK bootstrap S3 asset bucket as part of normal asset publishing, so no network call to the public chart repository is required during `cdk deploy`.

## Requirements

### Requirement 1: VPC and EKS Cluster Provisioning

**User Story:** As a platform engineer, I want the CDK stack to provision a minimal, cost-capped VPC and EKS cluster, so that I have a real, deployable Kubernetes environment in my personal AWS account without excess cost.

#### Acceptance Criteria

1. WHEN the CDK stack is synthesized THEN the system SHALL create a new VPC with `nat_gateways=1`.
2. WHEN the CDK stack is synthesized THEN the system SHALL create an EKS cluster using the `aws_cdk.aws_eks` module (not `aws_eks_v2`) with `version=eks.KubernetesVersion.V1_31` and a `KubectlV31Layer` kubectl layer.
3. WHEN the CDK stack is synthesized THEN the system SHALL configure the EKS cluster with `endpoint_access=eks.EndpointAccess.PUBLIC_AND_PRIVATE`.
4. WHEN the CDK stack is synthesized THEN the system SHALL add a managed EC2 node group to the cluster with instance type `t3.medium` and a fixed size of 1 (min=1, max=1, desired=1).

### Requirement 2: SSM Environment Parameter

**User Story:** As a platform engineer, I want the account environment name stored in a well-known SSM parameter, so that other resources (the Lambda) can read a single source of truth for the deployment environment.

#### Acceptance Criteria

1. WHEN the CDK stack is deployed THEN the system SHALL create an SSM `StringParameter` named `/platform/account/env` as a stack-owned resource that always exists whenever the stack exists.
2. WHEN the CDK context value `env` is provided (e.g. `cdk deploy -c env=staging`) THEN the system SHALL set the SSM parameter's value to that context value.
3. IF the CDK context value `env` is not provided THEN the system SHALL default the SSM parameter's value to `development`.
4. The SSM parameter SHALL be created as a plain `StringParameter` (not `SecureString`), since it contains no secret data.

### Requirement 3: Lambda Environment-to-Replica-Count Mapping

**User Story:** As a platform engineer, I want a Lambda function that reads the environment SSM parameter and returns the correct ingress-nginx replica count, so that the Helm chart is configured appropriately per environment.

#### Acceptance Criteria

1. WHEN the Lambda handler `on_event` is invoked THEN the system SHALL call `boto3` `ssm.get_parameter` for `/platform/account/env`.
2. WHEN the SSM parameter value is `development` THEN the Lambda SHALL return `{"ReplicaCount": "1"}`.
3. WHEN the SSM parameter value is `staging` THEN the Lambda SHALL return `{"ReplicaCount": "2"}`.
4. WHEN the SSM parameter value is `production` THEN the Lambda SHALL return `{"ReplicaCount": "2"}`.
5. IF the SSM parameter does not exist (`ParameterNotFound`) THEN the Lambda SHALL let the exception propagate uncaught, with no caught/default fallback value.
6. IF the SSM parameter value is none of `development`, `staging`, or `production` THEN the Lambda SHALL raise an exception (`ValueError`) rather than returning a default replica count.
7. The Lambda handler code SHALL reside in `lambda/handler.py` and SHALL have no dependency on any file in `infrastructure/`.

### Requirement 4: Custom Resource / Provider Wiring

**User Story:** As a platform engineer, I want the Lambda wrapped in CDK's Provider framework, so that CloudFormation custom resource signaling is handled correctly without hand-rolled response logic.

#### Acceptance Criteria

1. WHEN the CDK stack is synthesized THEN the system SHALL define the Lambda function's code via `lambda_.Code.from_asset("../lambda")`, referencing the `lambda/` folder by relative path only.
2. WHEN the CDK stack is synthesized THEN the system SHALL wrap the Lambda in an `aws_cdk.custom_resources.Provider` as the `on_event_handler`, and SHALL create an `aws_cdk.CustomResource` using that provider's `service_token`.
3. The system SHALL NOT implement manual CloudFormation custom resource response (PUT) logic; all response signaling SHALL be delegated to the `Provider` framework.
4. WHEN the Custom Resource is created or updated THEN the system SHALL ensure the SSM parameter resource is created before the Custom Resource attempts to read it (explicit dependency).
5. The Custom Resource SHALL expose exactly one attribute, `ReplicaCount`, as a string value ("1" or "2").

### Requirement 5: IAM Least Privilege for Lambda

**User Story:** As a security-conscious platform engineer, I want the Lambda's IAM permissions scoped to only what it needs, so that the deployment follows least-privilege principles.

#### Acceptance Criteria

1. WHEN the CDK stack is synthesized THEN the system SHALL grant the Lambda's execution role `ssm:GetParameter` permission scoped to exactly the `/platform/account/env` parameter ARN, via the SSM parameter's `grant_read()` method.
2. The system SHALL NOT grant the Lambda any wildcard SSM resource access (e.g. `parameter/*`).

### Requirement 6: Helm Chart Installation with Derived Replica Count

**User Story:** As a platform engineer, I want the ingress-nginx Helm chart installed into the EKS cluster from a locally vendored chart with a replica count derived from the environment, so that staging/production get more replicas than development without depending on a public chart repository being reachable at deploy time.

#### Acceptance Criteria

1. WHEN the CDK stack is synthesized THEN the system SHALL install the `ingress-nginx` Helm chart, chart version `4.15.1`, using a vendored `chart_asset` (an `aws_cdk.aws_s3_assets.Asset`) sourced from the repo-committed directory `infrastructure/charts/ingress-nginx/` (obtained via `helm pull ingress-nginx --repo https://kubernetes.github.io/ingress-nginx --version 4.15.1 --untar`), into the EKS cluster.
2. WHEN the Helm chart is configured THEN the system SHALL derive `controller.replicaCount` from `Token.as_number(custom_resource.get_att("ReplicaCount"))`, where `custom_resource` is the Custom Resource from Requirement 4.
3. The Helm chart installation SHALL NOT be wired into any other cluster resource beyond the cluster itself, per assignment scope.
4. WHEN the resolved environment is `development` THEN the deployed Helm release's `controller.replicaCount` SHALL be `1`.
5. WHEN the resolved environment is `staging` or `production` THEN the deployed Helm release's `controller.replicaCount` SHALL be `2`.
6. THE system SHALL NOT depend on network access to a public Helm chart repository (e.g. `https://kubernetes.github.io/ingress-nginx`) at deploy time, since the chart source is the local, repo-committed `chart_asset` directory.

### Requirement 7: Lambda Unit Test Coverage

**User Story:** As a developer, I want automated unit tests for the Lambda's environment-to-replica-count logic, so that the mapping behavior is verified without needing a live AWS deployment.

#### Acceptance Criteria

1. The system SHALL provide pytest unit tests located in `lambda/tests/`, covering only the Python code in `lambda/`.
2. The system SHALL NOT provide pytest unit tests for the CDK code in `infrastructure/`.
3. WHEN tests mock AWS services THEN the system SHALL use `moto`'s `mock_aws` decorator/context manager to mock the real `boto3` SSM `get_parameter`/`put_parameter` call shape, rather than hand-mocking the `boto3` client with a stub.
4. The test suite SHALL include a test case asserting `on_event` returns `{"ReplicaCount": "1"}` when the SSM parameter value is `development`.
5. The test suite SHALL include a test case asserting `on_event` returns `{"ReplicaCount": "2"}` when the SSM parameter value is `staging`.
6. The test suite SHALL include a test case asserting `on_event` returns `{"ReplicaCount": "2"}` when the SSM parameter value is `production`.
7. The test suite SHALL include a test case asserting `on_event` raises an exception (propagating `ParameterNotFound`) when the SSM parameter does not exist.
8. WHEN the test suite is run with coverage measurement (`pytest-cov`) THEN it SHALL achieve 100% line coverage of `lambda/handler.py`.

### Requirement 8: Repository Structure and Folder Isolation

**User Story:** As a team lead assigning this work to two engineers/agents in parallel, I want the Lambda code and CDK code fully isolated into separate top-level folders, so that both can be worked on simultaneously without file conflicts.

#### Acceptance Criteria

1. The system SHALL organize the Lambda handler, its runtime requirements, its dev/test requirements, and its tests entirely under a top-level `lambda/` folder.
2. The system SHALL organize the CDK app entrypoint, stack definitions, `cdk.json`, and CDK requirements entirely under a top-level `infrastructure/` folder.
3. The system SHALL NOT introduce any shared source file between `lambda/` and `infrastructure/`; the only permitted coupling SHALL be the relative asset path string used in `lambda_.Code.from_asset("../lambda")` and the `ReplicaCount` attribute contract.
4. WHEN either folder is modified THEN no change SHALL require modifying a file inside the other folder for that folder's own build/test to succeed (i.e., `lambda/`'s pytest suite runs independently of `infrastructure/`, and `infrastructure/`'s `cdk synth` does not require running Lambda tests).
