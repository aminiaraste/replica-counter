"""CDK stack for the EKS ingress replica-count feature.

This module currently implements:

* Task 5 - the VPC and EKS cluster (with a single managed node group).
* Task 6 - the ``/platform/account/env`` SSM ``StringParameter``.

The Lambda / Provider / CustomResource wiring (task 7) and the Helm chart
install (task 8) are added to this same stack in later tasks. See
``.kiro/specs/eks-ingress-replica-config/design.md`` for the full design.
"""

from aws_cdk import Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_eks as eks
from aws_cdk import aws_ssm as ssm
from aws_cdk.lambda_layer_kubectl_v32 import KubectlV32Layer
from constructs import Construct

# Default environment name used when no ``-c env=...`` context value is given.
DEFAULT_ENV = "development"

# Well-known SSM parameter name that holds the account environment.
ENV_PARAMETER_NAME = "/platform/account/env"


class EksStack(Stack):
    """Provisions the VPC, EKS cluster, and the account environment SSM parameter."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Task 6: SSM environment parameter -----------------------------
        # Sourced from CDK context key "env" (e.g. `cdk deploy -c env=staging`),
        # defaulting to "development". Always created as a stack-owned resource,
        # so the parameter exists whenever the stack exists. Plain StringParameter
        # (not SecureString) since the environment name is not a secret.
        env_name = self.node.try_get_context("env") or DEFAULT_ENV

        self.env_parameter = ssm.StringParameter(
            self,
            "AccountEnvParam",
            parameter_name=ENV_PARAMETER_NAME,
            string_value=env_name,
        )

        # --- Task 5.1: VPC -------------------------------------------------
        # Single NAT gateway to cap cost (deliberate, not HA). Default subnet
        # configuration (public + private) is sufficient for EKS managed node
        # groups.
        self.vpc = ec2.Vpc(self, "Vpc", nat_gateways=1)

        # --- Task 5.2: EKS cluster -----------------------------------------
        # Uses the original aws_eks module (not aws_eks_v2), Kubernetes 1.32
        # with the matching kubectl layer, and public + private endpoint access
        # so kubectl can reach the cluster from a personal machine without a
        # VPN or bastion.
        self.cluster = eks.Cluster(
            self,
            "Cluster",
            version=eks.KubernetesVersion.V1_32,
            kubectl_layer=KubectlV32Layer(self, "KubectlLayer"),
            endpoint_access=eks.EndpointAccess.PUBLIC_AND_PRIVATE,
            vpc=self.vpc,
            default_capacity=0,
        )

        # --- Task 5.3: Managed node group ----------------------------------
        # Single t3.medium node (min=1/max=1/desired=1) for cost-consciousness.
        # AL2023 AMI: EKS stopped publishing AL2 AMIs (the old CDK default) on
        # November 26, 2025, and AL2 no longer receives security patches.
        self.cluster.add_nodegroup_capacity(
            "NodeGroup",
            instance_types=[ec2.InstanceType("t3.medium")],
            ami_type=eks.NodegroupAmiType.AL2023_X86_64_STANDARD,
            min_size=1,
            max_size=1,
            desired_size=1,
        )
