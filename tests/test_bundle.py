# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path
import yaml

import lightkube.codecs
from lightkube import Client
from lightkube.generic_resource import create_namespaced_resource
from lightkube.resources.apiextensions_v1 import CustomResourceDefinition
from lightkube.resources.core_v1 import Service
import pytest
from pytest_operator.plugin import OpsTest
import requests
from tenacity import (
    Retrying,
    stop_after_delay,
    wait_fixed,
)


log = logging.getLogger(__name__)

KSVC = create_namespaced_resource(
    group="serving.knative.dev", version="v1", kind="Service", plural="services"
)
KNATIVE_SERVING_SERVICE = "services.serving.knative.dev"
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
KNATIVE_OPERATOR_IMAGE = METADATA["resources"]["knative-operator-image"]["upstream-source"]
KNATIVE_OPERATOR_RESOURCES = {"knative-operator-image": KNATIVE_OPERATOR_IMAGE}


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
    await ops_test.model.deploy(
        knative_charms["knative-operator"],
        application_name="knative-operator",
        trust=True,
        resources=KNATIVE_OPERATOR_RESOURCES,
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


RETRY_FOR_THREE_MINUTES = Retrying(
    stop=stop_after_delay(60 * 3),
    wait=wait_fixed(5),
    reraise=True,
)


@pytest.fixture()
def wait_for_ksvc():
    """Waits until KNative Serving Service is available, to a maximum 1 minute"""
    lightkube_client = Client()
    log.info("Waiting on ksvc to exist")
    for attempt in RETRY_FOR_THREE_MINUTES:
        with attempt:
            log.info("Checking for ksvc CRD")
            crd = lightkube_client.get(CustomResourceDefinition, KNATIVE_SERVING_SERVICE)


@pytest.fixture()
def remove_cloudevents_player_example(ops_test: OpsTest):
    """Fixture that attempts to remove the cloudevents-player example after a test has run"""
    yield
    lightkube_client = Client()
    lightkube_client.delete(KSVC, "cloudevents-player", namespace=ops_test.model_name)


def wait_for_ready(resource, name, namespace):
    """Waits for a ksvc to to be ready, to a maximum of timeout seconds."""
    lightkube_client = Client()

    timeout_error = TimeoutError("Timed out waiting for ksvc to be ready")

    for attempt in RETRY_FOR_THREE_MINUTES:
        with attempt:
            log.info("Checking ksvc status")
            # Validate that ksvc has "Ready" status and pass this loop, or raise an exception to
            # trigger the next attempt
            ksvc = lightkube_client.get(res=resource, name=name, namespace=namespace)
            status = ksvc.status
            if status is None:
                # status not yet available
                log.info("Waiting on ksvc for status to be available")
                raise timeout_error

            conditions = [c for c in status.get("conditions", []) if c["status"] == "True"]
            log.info(f"Waiting on ksvc with conditions {conditions} to be Ready")

            # Raise if ksvc is not ready
            if not any(c["type"] == "Ready" for c in conditions):
                raise timeout_error


async def test_cloud_events_player_example(
    ops_test: OpsTest, wait_for_ksvc, remove_cloudevents_player_example
):
    manifest = lightkube.codecs.load_all_yaml(
        Path("./examples/cloudevents-player.yaml").read_text()
    )
    lightkube_client = Client()

    for obj in manifest:
        lightkube_client.create(obj, namespace=ops_test.model_name)

    wait_for_ready(resource=KSVC, name="cloudevents-player", namespace=ops_test.model_name)

    gateway_svc = lightkube_client.get(
        Service, "istio-ingressgateway-workload", namespace=ops_test.model_name
    )
    gateway_ip = gateway_svc.status.loadBalancer.ingress[0].ip

    url = f"http://cloudevents-player.{ops_test.model_name}.{gateway_ip}.nip.io"
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
