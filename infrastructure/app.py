#!/usr/bin/env python3
"""CDK application entrypoint for the EKS ingress replica-count stack.

The stack reads the target environment from the CDK context key ``env``
(e.g. ``cdk deploy -c env=staging``), defaulting to ``development``. The
account/region come from the standard CDK environment variables populated by
the CLI, so `cdk synth` works without hardcoding an account.
"""

import os

import aws_cdk as cdk

from stacks.eks_stack import EksStack

app = cdk.App()

EksStack(
    app,
    "EksIngressReplicaConfigStack",
    # Use the CLI-provided account/region so the stack is environment-aware for
    # deploys while still synthesizing anywhere. These are set by the CDK CLI
    # from the active AWS credentials/profile.
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION"),
    ),
)

app.synth()
