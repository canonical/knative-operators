# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
from time import sleep
from typing import Dict, List

import pytest
import pytest_asyncio
import requests
import yaml
from pytest_operator.plugin import OpsTest

log = logging.getLogger(__name__)


@pytest_asyncio.fixture
async def gateway_ip(ops_test: OpsTest) -> str:
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
    return gateway_obj["status"]["loadBalancer"]["ingress"][0]["ip"]


def send_message(url: str) -> requests.Response:
    data = {"msg": "Hello CloudEvents!"}
    headers = {
        "Content-Type": "application/json",
        "Ce-Id": "123456789",
        "Ce-Specversion": "1.0",
        "Ce-Type": "some-type",
        "Ce-Source": "command-line",
    }
    response = requests.post(url, json=data, headers=headers, allow_redirects=False, verify=False)
    if response.status_code != 202:
        raise Exception(f"Failed to send message for url: {url}")

    return response


def get_player_received_messages(player_url: str) -> List[Dict]:
    response = requests.get(f"{player_url}/messages", allow_redirects=False, verify=False)

    if response.status_code != 200:
        raise Exception(f"Failed get request for player: {player_url}")

    messages = response.json()
    received_messages = list(
        filter(lambda message: message.get("type", None) == "RECEIVED", messages)
    )

    return received_messages


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
    # Build knative charms
    charms_path = "./charms/knative"
    knative_charms = await ops_test.build_charms(
        f"{charms_path}-operator", f"{charms_path}-serving", f"{charms_path}-eventing"
    )

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

    # Deploy knative charms
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


async def test_cloud_events_players_created(ops_test: OpsTest):
    await ops_test.run(
        "kubectl",
        "apply",
        "-f",
        "./examples/cloudevents-players.yaml",
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
    await ops_test.run(
        "kubectl",
        "wait",
        "--for=condition=ready",
        "ksvc",
        "cloudevents-player2",
        "--timeout=5m",
        check=True,
    )


async def test_broker_created(ops_test: OpsTest):
    await ops_test.run(
        "kubectl",
        "apply",
        "-f",
        "./examples/test-broker.yaml",
        check=True,
    )

    await ops_test.run(
        "kubectl",
        "wait",
        "--for=condition=ready",
        "broker",
        "test-broker",
        "--timeout=5m",
        check=True,
    )


async def test_triggers_and_sinks_created(ops_test: OpsTest):
    await ops_test.run(
        "kubectl",
        "apply",
        "-f",
        "./examples/cloudevents-triggers.yaml",
        check=True,
    )

    await ops_test.run(
        "kubectl",
        "wait",
        "--for=condition=ready",
        "trigger",
        "cloudevents-trigger",
        "--timeout=5m",
        check=True,
    )

    await ops_test.run(
        "kubectl",
        "wait",
        "--for=condition=ready",
        "trigger",
        "cloudevents-trigger2",
        "--timeout=5m",
        check=True,
    )


def test_message_sent_to_broker_and_received_by_each_sink(gateway_ip: str, ops_test: OpsTest):
    namespace = "default"
    url_player1 = f"http://cloudevents-player.{namespace}.{gateway_ip}.nip.io"
    url_player2 = f"http://cloudevents-player2.{namespace}.{gateway_ip}.nip.io"

    _ = send_message(f"{url_player1}/messages")

    sleep(10)  # wait for message to be processed

    messages1 = get_player_received_messages(url_player1)
    messages2 = get_player_received_messages(url_player2)

    assert len(messages1) == 1
    assert len(messages2) == 1
