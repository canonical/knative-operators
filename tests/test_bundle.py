# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import pytest
import yaml
from pytest_operator.plugin import OpsTest

log = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
async def test_kubectl_access(ops_test: OpsTest):
    """Fails if kubectl not available or if no cluster context exists"""
    _, stdout, _ = await ops_test.run(
        "kubectl",
        "config",
        "view",
        check=True,
        fail_msg="Failed to execute kubectl - is kubectl installed?",
    )

    # Check if kubectl has a context, failing if it does not
    kubectl_config = yaml.safe_load(stdout)
    error_message = (
        "Found no kubectl contexts - did you populate KUBECONFIG?  Ex:"
        " 'KUBECONFIG=/home/runner/.kube/config tox ...' or"
        " 'KUBECONFIG=/home/runner/.kube/config tox ...'"
    )
    assert kubectl_config["contexts"] is not None, error_message

    await ops_test.run(
        "kubectl",
        "get",
        "pods",
        check=True,
        fail_msg="Failed to do a simple kubectl task - is KUBECONFIG properly configured?",
    )


@pytest.mark.abort_on_fail
async def test_build_deploy_knative_charms(ops_test: OpsTest):
    # Build and deploy knative charms
    charms_path = "./charms/knative"
    knative_charms = await ops_test.build_charms(
        f"{charms_path}-operator", f"{charms_path}-serving", f"{charms_path}-eventing"
    )

    # TODO: Remove httpbin-image argument from `resource` parameter
    # once we populate charms/knative-* with knative specific code
    knative_operator_image = "gcr.io/knative-releases/knative.dev/operator/cmd/operator:v1.1.0"
    await ops_test.model.deploy(
        knative_charms["knative-operator"],
        application_name="knative-operator",
        trust=True,
        resources={"knative-operator-image": knative_operator_image},
    )

    await ops_test.model.deploy(
        knative_charms["knative-serving"],
        application_name="knative-serving",
        trust=True,
        resources={"httpbin-image": "kennethreitz/httpbin"},
    )

    await ops_test.model.deploy(
        knative_charms["knative-eventing"],
        application_name="knative-eventing",
        trust=True,
        resources={"httpbin-image": "kennethreitz/httpbin"},
    )

    await ops_test.model.wait_for_idle(
        status="active",
        raise_on_blocked=False,
        timeout=90 * 10,
    )


@pytest.mark.abort_on_fail
async def test_example(ops_test: OpsTest):
    # This is a placeholder test case
    pass
