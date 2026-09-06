# replica-counter

A Python CDK project that provisions an Amazon EKS cluster and installs the `ingress-nginx` Helm chart with a `controller.replicaCount` value derived at deploy time from an SSM parameter, via a Lambda-backed CloudFormation Custom Resource.

See [`assignment/eks_assignment.md`](assignment/eks_assignment.md) for the original task description.

## How it works

1. The CDK stack creates a VPC, an EKS cluster with a managed node group, and an SSM `StringParameter` at `/platform/account/env` (value: `development`, `staging`, or `production`, set via CDK context).
2. A Lambda function (`lambda/handler.py`), wrapped in a CDK `custom_resources.Provider`, reads that SSM parameter with `boto3` and returns a `ReplicaCount` attribute:
   - `development` -> `"1"`
   - `staging` / `production` -> `"2"`
3. The CDK stack passes that value into the `ingress-nginx` Helm chart install (`controller.replicaCount`) via a `CustomResource`.

## Repository layout

```
replica-counter/
├── assignment/              # Original assignment description
├── lambda/                  # Lambda handler + its own pytest suite (isolated)
│   ├── handler.py
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   └── tests/
└── infrastructure/          # CDK app, stack, and its own dependencies (isolated)
    ├── app.py
    ├── cdk.json
    ├── requirements.txt
    └── stacks/
```

`lambda/` and `infrastructure/` are self-contained and can be developed independently. The only coupling between them is the relative asset path `lambda_.Code.from_asset("../lambda")` and the `ReplicaCount` attribute contract.

Full requirements and design details live in `.kiro/specs/eks-ingress-replica-config/`.

## Prerequisites

- Python 3.12+
- AWS CLI configured with credentials for your target account
- [AWS CDK CLI](https://docs.aws.amazon.com/cdk/v2/guide/getting_started.html) (`npm install -g aws-cdk`)
- An AWS account bootstrapped for CDK (`cdk bootstrap`)

## Lambda: setup and tests

```bash
cd lambda
python -m venv .venv
.venv\Scripts\activate      # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt

pytest --cov=handler --cov-report=term-missing
```

## Infrastructure: setup and deploy

```bash
cd infrastructure
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# First time only, per account/region
cdk bootstrap

# Review generated CloudFormation
cdk synth

# Deploy with default environment (development -> replicaCount 1)
cdk deploy

# Deploy explicitly as staging or production -> replicaCount 2
cdk deploy -c env=staging
cdk deploy -c env=production
```

## Notes

- The `ingress-nginx` chart is fetched at deploy time from the public repository `https://kubernetes.github.io/ingress-nginx`, pinned to chart version `4.15.1`. CDK's kubectl/Helm provider Lambda runs in the VPC's private subnets and reaches the repository through the stack's NAT gateway, so a deploy requires that repository to be reachable. Bumping the chart is an explicit edit to the pinned version.
- The Lambda's IAM permissions are scoped to `ssm:GetParameter` on exactly the `/platform/account/env` parameter, no wildcards.
- This stack is sized for cost-consciousness (single NAT gateway, single `t3.medium` node) for use in a personal AWS account, not production HA.
