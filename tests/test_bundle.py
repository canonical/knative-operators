# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging

import pytest
import requests
import yaml
from lightkube.models.core_v1 import Service
from pytest_operator.plugin import OpsTest

log = logging.getLogger(__name__)


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

async def test_cloud_events_player_example(ops_test: OpsTest, lightkube_client, KnativeService_v1):
    with open("examples/cloudevents-player.yaml") as f:
        ksvc = KnativeService_v1(yaml.safe_load(f.read()))
        lightkube_client.apply(ksvc)
    await lightkube_client.wait(KnativeService_v1, "cloudevents-player", for_conditions=["ready"])
    gateway_json = lightkube_client.get(Service, "istio-ingressgateway-workload", namespace=ops_test.model_name)
    gateway_obj = json.loads(gateway_json[1])
    gateway_ip = gateway_obj["status"]["loadBalancer"]["ingress"][0]["ip"]
    url = f"http://cloudevents-player.default.{gateway_ip}.nip.io"
    data = {"msg": "Hello CloudEvents!"}
    headers = {
        "Content-Type": "application/json",
        "Ce-Id": "123456789",
        "Ce-Specversion": "1.0",
        "Ce-Type": "some-type",
        "Ce-Source": "command-line",
    }
    post_req = requests.post(url, json=data, headers=headers, allow_redirects=False, verify=False)
    assert post_req.status_code == 202
    get_req = requests.get(f"{url}/messages", allow_redirects=False, verify=False)
    assert get_req.status_code == 200
