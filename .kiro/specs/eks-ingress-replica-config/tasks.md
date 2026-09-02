# Implementation Plan: EKS Ingress Replica Config

## Overview

This plan implements the design in `design.md`: a CDK stack that provisions a VPC and EKS cluster, reads an environment-driven SSM parameter, resolves a replica count via a custom-resource-backed Lambda, and installs the `ingress-nginx` Helm chart with that replica count. Lambda code (`lambda/`) and infrastructure code (`infrastructure/`) are kept independent and are wired together only in the Provider/CustomResource step.

## Tasks

- [x] 1. Scaffold repository layout
  - Create top-level `lambda/` and `infrastructure/` folders as described in design.md's Repository Layout section.
  - Create empty placeholders: `lambda/tests/`, `infrastructure/stacks/`.
  - _Requirements: 8.1, 8.2_

- [ ] 2. Implement Lambda handler (`lambda/`)
  - [ ] 2.1 Write `lambda/handler.py` with `on_event(event, context)`
    - Call `boto3.client("ssm").get_parameter(Name="/platform/account/env")`.
    - Map `development` -> `{"ReplicaCount": "1"}`, `staging`/`production` -> `{"ReplicaCount": "2"}`.
    - Raise `ValueError` for any other value; let `ParameterNotFound` propagate uncaught (no try/except around the get_parameter call).
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_
  - [ ] 2.2 Write `lambda/requirements.txt` and `lambda/requirements-dev.txt`
    - `requirements.txt`: document that boto3 is preinstalled in the Lambda runtime (leave empty or add a comment).
    - `requirements-dev.txt`: pin `pytest`, `pytest-cov`, `moto` to specific versions.
    - _Requirements: 3.7_

- [ ] 3. Write Lambda unit tests with moto
  - [ ] 3.1 Write `lambda/tests/test_handler.py` covering development/staging/production/missing-parameter cases
    - Use `@mock_aws` and real `ssm.put_parameter` calls to set up state (no hand-mocked boto3 stub).
    - Assert `on_event({}, None)` returns `{"ReplicaCount": "1"}` for `development`.
    - Assert `on_event({}, None)` returns `{"ReplicaCount": "2"}` for `staging` and for `production`.
    - Assert `on_event({}, None)` raises when the parameter is absent under `mock_aws`.
    - _Requirements: 7.1, 7.3, 7.4, 7.5, 7.6, 7.7_
  - [ ] 3.2 Run `pytest --cov=handler --cov-report=term-missing` in `lambda/` and confirm 100% coverage of `handler.py`
    - Add any missing branch coverage (e.g. the unexpected-value `ValueError` path) if the report shows gaps.
    - _Requirements: 7.2, 7.8_

- [x] 4. Implement CDK app skeleton (`infrastructure/`)
  - [x] 4.1 Write `infrastructure/cdk.json` and `infrastructure/requirements.txt`
    - `requirements.txt`: pin `aws-cdk-lib`, `constructs`, `aws-cdk.lambda-layer-kubectl-v31`. `aws_cdk.aws_s3_assets` is part of `aws-cdk-lib` in CDK v2 — no separate package needed.
    - _Requirements: none directly (supports all infra requirements)_
  - [x] 4.2 Write `infrastructure/app.py` instantiating the stack, passing through CDK context
    - _Requirements: 2.2, 2.3_
  - [x] 4.3 Vendor the `ingress-nginx` Helm chart into the repo
    - One-time, manual setup step (not part of automated build/deploy; requires the `helm` CLI installed locally as a prerequisite): run `helm pull ingress-nginx --repo https://kubernetes.github.io/ingress-nginx --version 4.15.1 --untar`.
    - Commit the resulting extracted chart directory to `infrastructure/charts/ingress-nginx/`.
    - _Requirements: 6.1, 6.3_

- [x] 5. Implement VPC and EKS cluster in the stack
  - [x] 5.1 In `infrastructure/stacks/eks_stack.py`, create the VPC with `nat_gateways=1`
    - _Requirements: 1.1_
  - [x] 5.2 Create the EKS cluster via `aws_cdk.aws_eks.Cluster` with `KubernetesVersion.V1_31`, `KubectlV31Layer`, `EndpointAccess.PUBLIC_AND_PRIVATE`, and the VPC from 5.1
    - _Requirements: 1.2, 1.3_
  - [x] 5.3 Add the managed EC2 node group (`t3.medium`, min=1/max=1/desired=1) via `cluster.add_nodegroup_capacity`
    - _Requirements: 1.4_

- [x] 6. Implement SSM parameter in the stack
  - [x] 6.1 Create the `StringParameter` `/platform/account/env`, sourcing its value from `scope.node.try_get_context("env")` defaulting to `"development"`
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [ ] 7. Implement Lambda function resource, IAM grant, and Provider/CustomResource wiring
  - [ ] 7.1 Define the `aws_cdk.aws_lambda.Function` resource with `code=lambda_.Code.from_asset("../lambda")` and handler `handler.on_event`
    - _Requirements: 4.1_
  - [ ] 7.2 Grant least-privilege read access via `ssm_param.grant_read(handler)`
    - _Requirements: 5.1, 5.2_
  - [ ] 7.3 Wrap the function in `custom_resources.Provider` and create the `CustomResource` with `service_token=provider.service_token`
    - _Requirements: 4.2, 4.3, 4.5_
  - [ ] 7.4 Add an explicit dependency from the Custom Resource (or its underlying resource) on the SSM parameter
    - _Requirements: 4.4_

- [ ] 8. Implement Helm chart installation with derived replica count
  - [ ] 8.1 Compute `replica_count = Token.as_number(custom_resource.get_att("ReplicaCount"))`
    - _Requirements: 6.2_
  - [ ] 8.2 Install the `ingress-nginx` Helm chart from the vendored chart asset via `s3_assets.Asset(scope, "IngressNginxChartAsset", path="./charts/ingress-nginx")` and `cluster.add_helm_chart(..., chart_asset=chart_asset, values={"controller": {"replicaCount": replica_count}})`, not wired to any other resource, with no `chart`/`repository`/`version` properties set
    - _Requirements: 6.1, 6.3, 6.4, 6.5_

- [ ] 9. Verify end-to-end synthesis and isolation
  - [ ] 9.1 Run `cdk synth` in `infrastructure/` and confirm it succeeds without needing to run anything in `lambda/` beyond the asset files existing on disk
    - _Requirements: 8.3, 8.4_
  - [ ] 9.2 Confirm `lambda/`'s pytest suite runs and passes independently of `infrastructure/` (no CDK imports in `lambda/`)
    - _Requirements: 8.3, 8.4_

- [ ] 10. Deploy to AWS and verify end-to-end
  - [ ] 10.1 Bootstrap the CDK environment (`cdk bootstrap`) against account 577638398151, eu-central-1, if not already bootstrapped
    - Required because the Helm chart asset upload (task 8.2) depends on the CDK bootstrap S3 asset bucket existing.
    - _Requirements: 6.1_
  - [ ] 10.2 Deploy with default context (`cdk deploy` in `infrastructure/`) and verify the `development` result
    - Confirm the deploy completes successfully (no rollback/failure).
    - Verify `aws ssm get-parameter --name /platform/account/env` returns value `development`.
    - Verify via `kubectl get deployment -n <namespace>` (or `helm list` / `kubectl get pods`) that the ingress-nginx controller is running with 1 replica.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.3, 6.4_
  - [ ] 10.3 Redeploy with `cdk deploy -c env=staging` and verify the `staging` result
    - Confirm `aws ssm get-parameter --name /platform/account/env` now returns value `staging`.
    - Confirm the ingress-nginx controller scales to 2 replicas.
    - _Requirements: 2.2, 6.5_
  - [ ] 10.4 Confirm clean Lambda execution and CloudFormation status for both deploys
    - Confirm the Lambda's CloudWatch Logs show no errors during either the `development` or `staging` deploy.
    - Confirm the CustomResource shows `CREATE_COMPLETE` (first deploy) and `UPDATE_COMPLETE` (staging redeploy) in the CloudFormation console/CLI.
    - _Requirements: 4.2, 4.4, 4.5_
  - [ ] 10.5 Tear down the stack (`cdk destroy`) and confirm clean deletion
    - Run `cdk destroy` once verification is complete, to avoid ongoing cost on the personal account.
    - Confirm the stack deletes cleanly, including the EKS cluster, node group, NAT gateway, and VPC.
    - _Requirements: 1.1, 1.2, 1.4_

## Notes

- **Parallel-agent folder split**: `lambda/` (tasks 2-3) and `infrastructure/` (tasks 4-6) have no code dependency on each other and can be implemented in parallel by two different engineers/agents. They converge at task 7, where the CDK stack references the Lambda code as a deployment asset.
- **Moto-based coverage**: Lambda unit tests (task 3) must use `moto`'s `@mock_aws` with real `ssm.put_parameter` calls rather than hand-mocked boto3 stubs, and must reach 100% coverage of `handler.py` (task 3.2). Any coverage gap must be closed with additional test cases, not with `# pragma: no cover` exclusions.
- **Pinned versions**: Kubernetes version `1.31` (via `KubernetesVersion.V1_31` / `KubectlV31Layer`) and `ingress-nginx` chart version `4.15.1` are fixed by the design. Do not bump either without first updating `design.md`, since the CDK layer package and chart values schema are version-coupled.
- **Vendored chart**: the `ingress-nginx` chart is vendored into `infrastructure/charts/ingress-nginx/` (task 4.3) rather than fetched live from `https://kubernetes.github.io/ingress-nginx` at deploy time. Bumping the chart version requires re-running `helm pull ingress-nginx --repo https://kubernetes.github.io/ingress-nginx --version <new-version> --untar` and committing the new chart content — it does not update automatically.
- **Real AWS spend**: task 10 is the only task in this plan that incurs real billable AWS cost (EKS control plane, NAT gateway, EC2 node) in the personal account (577638398151, eu-central-1). It should be run last, only after tasks 1-9 (including the full Lambda test suite and `cdk synth`) pass. Always finish with `cdk destroy` (task 10.5) to avoid leaving the EKS cluster, NAT gateway, and other billable resources running.

## Task Dependency Graph

```mermaid
graph TD
  T1[1. Scaffold repository layout]
  T2[2. Implement Lambda handler]
  T3[3. Write Lambda unit tests]
  T4[4. Implement CDK app skeleton]
  T5[5. Implement VPC and EKS cluster]
  T6[6. Implement SSM parameter]
  T7[7. Provider/CustomResource wiring]
  T8[8. Helm chart with derived replica count]
  T9[9. Verify end-to-end synthesis and isolation]
  T10[10. Deploy to AWS and verify end-to-end]

  T1 --> T2
  T1 --> T4
  T2 --> T3
  T4 --> T5
  T4 --> T6
  T2 --> T7
  T5 --> T7
  T6 --> T7
  T7 --> T8
  T3 --> T9
  T8 --> T9
  T9 --> T10
```

Track split:
- Engineer/agent A (lambda/): 1 -> 2 -> 3
- Engineer/agent B (infrastructure/): 1 -> 4 -> 5, 6
- Convergence: 3 and (5, 6) feed into 7 -> 8 -> 9 -> 10

```json
{
  "waves": [
    { "wave": 1, "tasks": [1] },
    { "wave": 2, "tasks": [2, 4] },
    { "wave": 3, "tasks": [3, 5, 6] },
    { "wave": 4, "tasks": [7] },
    { "wave": 5, "tasks": [8] },
    { "wave": 6, "tasks": [9] },
    { "wave": 7, "tasks": [10] }
  ]
}
```
