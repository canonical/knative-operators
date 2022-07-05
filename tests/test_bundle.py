# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging

import pytest
import requests
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
    # Deploy istio as dependency
    await ops_test.model.deploy(
        "istio-pilot",
        channel="latest/edge",
        config={"default-gateway": "knative-gateway"},
        trust=True,
    )
    await ops_test.model.deploy(
        "istio-gateway",
        application_name="istio-ingressgateway",
        channel="latest/edge",
        config={"kind": "ingress"},
        trust=True,
    )
    await ops_test.model.add_relation("istio-pilot", "istio-ingressgateway")

    await ops_test.model.wait_for_idle(
        ["istio-pilot", "istio-ingressgateway"],
        raise_on_blocked=False,
        status="active",
        timeout=90 * 10,
    )

    # Build and deploy knative charms
    charms_path = "./charms/knative"
    knative_charms = await ops_test.build_charms(
        f"{charms_path}-operator", f"{charms_path}-serving", f"{charms_path}-eventing"
    )

    knative_operator_image = "gcr.io/knative-releases/knative.dev/operator/cmd/operator:v1.1.0"
    await ops_test.model.deploy(
        knative_charms["knative-operator"],
        application_name="knative-operator",
        trust=True,
        resources={"knative-operator-image": knative_operator_image},
    )

    await ops_test.model.wait_for_idle(
        ["knative-operator"],
        status="active",
        raise_on_blocked=False,
        timeout=90 * 10,
    )

    await ops_test.model.deploy(
        knative_charms["knative-serving"],
        application_name="knative-serving",
        config={"namespace": "knative-serving", "istio.gateway.namespace": ops_test.model_name},
        trust=True,
    )

    await ops_test.model.deploy(
        knative_charms["knative-eventing"],
        application_name="knative-eventing",
        config={"namespace": "knative-eventing"},
        trust=True,
    )

    await ops_test.model.wait_for_idle(
        ["knative-serving", "knative-eventing"],
        status="active",
        raise_on_blocked=False,
        timeout=90 * 10,
    )


async def test_cloud_events_player_example(ops_test: OpsTest):
    await ops_test.run(
        "kubectl",
        "apply",
        "-f",
        "./examples/cloudevents-player.yaml",
        check=True,
    )
    await ops_test.run(
        "kubectl",
        "wait",
        "--for=condition=ready",
        "ksvc",
        "cloudevents-player",
        "--timeout=5m",
        check=True,
    )

    gateway_json = await ops_test.run(
        "kubectl",
        "get",
        "services/istio-ingressgateway-workload",
        "-n",
        ops_test.model_name,
        "-ojson",
        check=True,
    )

    gateway_obj = json.loads(gateway_json[1])
    gateway_ip = gateway_obj["status"]["loadBalancer"]["ingress"][0]["ip"]
    url = f"http://cloudevents-player.default.{gateway_ip}.nip.io/messages"
    data = {"msg": "Hello CloudEvents!"}
    headers = {
        "Content-Type": "application/json",
        "Ce-Id": "123456789",
        "Ce-Specversion": "1.0",
        "Ce-Type": "some-type",
        "Ce-Source": "command-line",
    }
    post_req = requests.post(url, data=data, headers=headers, allow_redirects=False, verify=False)
    assert post_req.status_code == 202
    get_req = requests.get(url, allow_redirects=False, verify=False)
    assert get_req.status_code == 202
