"""CDK stack for the EKS ingress replica-count feature.

This module implements:

* Task 5 - the VPC and EKS cluster (with a single managed node group).
* Task 6 - the ``/platform/account/env`` SSM ``StringParameter``.
* Task 7 - the Lambda function resource, its least-privilege IAM grant, and
  the ``custom_resources.Provider`` / ``CustomResource`` wiring that exposes
  the derived ``ReplicaCount`` attribute.
* Task 8 - the ``ingress-nginx`` Helm chart install, from the vendored chart
  asset, with ``controller.replicaCount`` sourced from the custom resource.

See ``.kiro/specs/eks-ingress-replica-config/design.md`` for the full design.
"""

from aws_cdk import CustomResource, Duration, Stack, Token
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_eks as eks
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3_assets as s3_assets
from aws_cdk import aws_ssm as ssm
from aws_cdk import custom_resources as cr
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
        self.node_group = self.cluster.add_nodegroup_capacity(
            "NodeGroup",
            instance_types=[ec2.InstanceType("t3.medium")],
            ami_type=eks.NodegroupAmiType.AL2023_X86_64_STANDARD,
            min_size=1,
            max_size=1,
            desired_size=1,
        )

        # --- Task 7.1: Lambda function resource ----------------------------
        # The on-event handler for the custom resource. Its code is the sibling
        # ``lambda/`` folder, referenced as a deployment asset. This relative
        # path (plus the "ReplicaCount" attribute contract) is the only coupling
        # between the ``infrastructure/`` and ``lambda/`` folders. Python 3.12
        # runtime ships boto3 preinstalled, so ``lambda/requirements.txt`` is
        # intentionally empty.
        # ``exclude`` keeps the deployment asset limited to what the handler
        # needs at runtime. Without it, anything sitting in ``lambda/`` at
        # synth time - a local ``.venv``, pytest caches, dev-only requirements
        # - gets zipped up too, which risks the Lambda package-size limit and
        # churns the asset hash on every local test run.
        replica_count_handler = lambda_.Function(
            self,
            "ReplicaCountHandler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.on_event",
            code=lambda_.Code.from_asset(
                "../lambda",
                exclude=[
                    ".venv",
                    "tests",
                    "__pycache__",
                    "*.pyc",
                    ".pytest_cache",
                    ".coverage",
                    "requirements-dev.txt",
                ],
            ),
            # Cold start (import boto3, build the SSM client, one network
            # call) can exceed the CDK default 3s timeout, which would fail
            # the custom resource and roll back the whole stack after the
            # EKS cluster has already been created. This runs once per
            # deploy, so a generous timeout costs nothing.
            timeout=Duration.seconds(30),
        )

        # --- Task 7.2: Least-privilege IAM grant ---------------------------
        # Grants ssm:GetParameter (and related read actions) scoped to exactly
        # the one parameter ARN, no wildcards. ``grant_read`` attaches the
        # policy to the Lambda's execution role.
        self.env_parameter.grant_read(replica_count_handler)

        # --- Task 7.3: Provider + CustomResource ---------------------------
        # The Provider framework handles all CloudFormation response signaling,
        # so the Lambda never has to PUT a response itself. The CustomResource
        # exposes the "ReplicaCount" attribute returned by the handler.
        replica_count_provider = cr.Provider(
            self,
            "ReplicaCountProvider",
            on_event_handler=replica_count_handler,
        )

        # ``EnvironmentName`` is not read by the handler (it re-reads SSM
        # directly, per Requirement 3.1) - it exists purely so the custom
        # resource's own properties change whenever ``env`` changes.
        # CloudFormation only re-invokes a custom resource's Lambda on
        # Update when its properties differ from the last deployed state;
        # without this, switching from `-c env=development` to
        # `-c env=staging` would update the SSM parameter but never
        # re-trigger the Lambda, leaving ReplicaCount (and therefore the
        # Helm release's replica count) stuck at its first-deploy value.
        replica_count_resource = CustomResource(
            self,
            "ReplicaCountResource",
            service_token=replica_count_provider.service_token,
            properties={"EnvironmentName": env_name},
        )

        # --- Task 7.4: Explicit dependency on the SSM parameter ------------
        # Ensures the parameter is written before the custom resource runs the
        # Lambda that reads it, on both create and update.
        replica_count_resource.node.add_dependency(self.env_parameter)

        # --- Task 8.1: Derived replica count -------------------------------
        # ``get_att`` yields a CloudFormation string token; ``Token.as_number``
        # defers the string->number coercion to deploy time, sidestepping
        # Fn::GetAtt's string-only limitation without JSON parsing.
        replica_count = Token.as_number(
            replica_count_resource.get_att("ReplicaCount")
        )

        # --- Task 8.2: ingress-nginx Helm chart install --------------------
        # Installed from the vendored chart directory (v4.15.1) rather than a
        # live repo fetch: CDK zips ``charts/ingress-nginx`` and uploads it to
        # the bootstrap asset bucket. ``chart_asset`` is mutually exclusive with
        # ``chart``/``repository``/``version`` (exactly one of ``chart`` or
        # ``chart_asset`` may be set), so those are intentionally omitted.
        ingress_nginx_chart_asset = s3_assets.Asset(
            self,
            "IngressNginxChartAsset",
            path="./charts/ingress-nginx",
        )

        ingress_nginx_helm_chart = self.cluster.add_helm_chart(
            "IngressNginx",
            chart_asset=ingress_nginx_chart_asset,
            values={"controller": {"replicaCount": replica_count}},
            # Explicit, stable release name instead of the auto-generated
            # (and truncated) default, so `helm list`/`kubectl` verification
            # in task 10 has a predictable name to look for.
            release="ingress-nginx",
            # Block until the chart's resources report ready, so a stuck
            # rollout (e.g. the single t3.medium node can't fit both the
            # controller and default-backend pods) fails `cdk deploy`
            # itself rather than surfacing only during manual verification.
            wait=True,
        )

        # Explicit dependency on the node group. `add_helm_chart` only
        # implicitly depends on the cluster's kubectl provider being ready,
        # not on any particular node group being ACTIVE with nodes joined.
        # Without this, the Helm install's kubectl/Helm Lambda can run
        # while the control plane's networking to worker/handler ENIs is
        # still settling right after cluster + node group creation, which
        # has been observed to fail with a control-plane connection timeout
        # ("Kubernetes cluster unreachable: dial tcp ...:443: i/o timeout").
        ingress_nginx_helm_chart.node.add_dependency(self.node_group)
