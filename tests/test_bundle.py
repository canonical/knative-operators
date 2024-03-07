# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time
from pathlib import Path

import lightkube.codecs
import pytest
import pytest_asyncio
import requests
import yaml
from lightkube import ApiError, Client
from lightkube.generic_resource import create_namespaced_resource
from lightkube.resources.apiextensions_v1 import CustomResourceDefinition
from lightkube.resources.apps_v1 import Deployment
from lightkube.resources.core_v1 import ConfigMap, Service
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_delay, wait_fixed

log = logging.getLogger(__name__)

KSVC = create_namespaced_resource(
    group="serving.knative.dev", version="v1", kind="Service", plural="services"
)
KNATIVE_EVENTING_NAMESPACE = "knative-eventing"
KNATIVE_SERVING_NAMESPACE = "knative-serving"
KNATIVE_SERVING_SERVICE = "services.serving.knative.dev"
KNATIVE_OPERATOR_METADATA = yaml.safe_load(
    Path("./charms/knative-operator/metadata.yaml").read_text()
)
KNATIVE_OPERATOR_IMAGE = KNATIVE_OPERATOR_METADATA["resources"]["knative-operator-image"][
    "upstream-source"
]
KNATIVE_OPERATOR_WEBHOOK_IMAGE = KNATIVE_OPERATOR_METADATA["resources"][
    "knative-operator-webhook-image"
]["upstream-source"]
KNATIVE_OPERATOR_RESOURCES = {
    "knative-operator-image": KNATIVE_OPERATOR_IMAGE,
    "knative-operator-webhook-image": KNATIVE_OPERATOR_WEBHOOK_IMAGE,
}


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
        config={
            "namespace": KNATIVE_SERVING_NAMESPACE,
            "istio.gateway.namespace": ops_test.model_name,
        },
        trust=True,
    )

    await ops_test.model.deploy(
        knative_charms["knative-eventing"],
        application_name="knative-eventing",
        config={"namespace": KNATIVE_EVENTING_NAMESPACE},
        trust=True,
    )

    await ops_test.model.wait_for_idle(
        ["knative-serving", "knative-eventing"],
        status="active",
        raise_on_blocked=False,
        timeout=90 * 10,
    )

    # Sleep here to avoid a race condition between the rest of the tests and knative
    # eventing/serving coming up.  This race condition is because of:
    # https://github.com/canonical/knative-operators/issues/50
    time.sleep(120)


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
            lightkube_client.get(CustomResourceDefinition, KNATIVE_SERVING_SERVICE)


@pytest.fixture()
def remove_cloudevents_player_example(ops_test: OpsTest):
    """Fixture that attempts to remove the cloudevents-player example after a test has run"""
    yield
    lightkube_client = Client()
    try:
        lightkube_client.delete(KSVC, "cloudevents-player", namespace=ops_test.model_name)
    except ApiError as e:
        # If the ksvc doesn't exist, we can ignore the error
        if e.code == 404:
            log.info("Tried to delete cloudevents-player knative service, but it didn't exist")
        else:
            raise e


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


@pytest_asyncio.fixture
async def restore_eventing_custom_image_settings(ops_test: OpsTest):
    """Saves the current custom_image setting for eventing, restoring it after test completes."""
    custom_image_config = (await ops_test.model.applications["knative-eventing"].get_config())[
        "custom_images"
    ]["value"]

    yield
    await ops_test.model.applications["knative-eventing"].set_config(
        {"custom_images": custom_image_config}
    )

    await ops_test.model.wait_for_idle(
        ["knative-eventing"],
        status="active",
        raise_on_blocked=False,
        timeout=60 * 1,
    )


async def test_eventing_custom_image(ops_test: OpsTest, restore_eventing_custom_image_settings):
    """Changes config to use a custom image for eventing-controller, then asserts it worked."""
    fake_image = "not-a-real-image"

    # Act
    await ops_test.model.applications["knative-eventing"].set_config(
        {"custom_images": f"eventing-controller/eventing-controller: {fake_image}"}
    )
    await ops_test.model.wait_for_idle(
        ["knative-eventing"],
        status="active",
        raise_on_blocked=False,
        timeout=60 * 1,
    )

    # Assert that the activator image is trying to use the custom image.
    client = lightkube.Client()
    activator_deployment = client.get(
        Deployment, "eventing-controller", namespace=KNATIVE_EVENTING_NAMESPACE
    )
    assert activator_deployment.spec.template.spec.containers[0].image == fake_image


@pytest_asyncio.fixture
async def restore_serving_custom_image_settings(ops_test: OpsTest):
    """Saves the current custom_image setting for serving, restoring it after test completes."""
    custom_image_config = (await ops_test.model.applications["knative-serving"].get_config())[
        "custom_images"
    ]["value"]

    yield
    await ops_test.model.applications["knative-serving"].set_config(
        {"custom_images": custom_image_config}
    )

    await ops_test.model.wait_for_idle(
        ["knative-serving"],
        status="active",
        raise_on_blocked=False,
        timeout=60 * 1,
    )


async def test_serving_custom_image(ops_test: OpsTest, restore_serving_custom_image_settings):
    """Changes config to use a custom image for the serving Activator, then asserts it worked."""
    fake_image = "not-a-real-image"

    # Act
    await ops_test.model.applications["knative-serving"].set_config(
        {"custom_images": f"activator: {fake_image}"}
    )
    await ops_test.model.wait_for_idle(
        ["knative-serving"],
        status="active",
        raise_on_blocked=False,
        timeout=60 * 1,
    )

    # Assert that the activator image is trying to use the custom image.
    client = lightkube.Client()
    activator_deployment = client.get(Deployment, "activator", namespace=KNATIVE_SERVING_NAMESPACE)
    assert activator_deployment.spec.template.spec.containers[0].image == fake_image


async def test_serving_config_progress_deadline(ops_test: OpsTest):
    """
    Changes `progress-deadline` config, then asserts the change took effect
    in the `config-deployment ConfigMap`
    """

    custom_deadline = "800s"

    # Act
    await ops_test.model.applications["knative-serving"].set_config(
        {"progress-deadline": custom_deadline}
    )
    await ops_test.model.wait_for_idle(
        ["knative-serving"],
        status="active",
        raise_on_blocked=False,
        timeout=60 * 1,
    )

    # Assert
    client = lightkube.Client()
    config_deployment_cm = client.get(
        ConfigMap, "config-deployment", namespace=KNATIVE_SERVING_NAMESPACE
    )
    assert config_deployment_cm.data["progress-deadline"] == custom_deadline


async def test_serving_config_registries_skip_tag_resolution(ops_test: OpsTest):
    """
    Changes `registries-skip-tag-resolution` config, then asserts the change took effect
    in the `config-deployment ConfigMap`
    """

    custom_registries = "dev.local"

    # Act
    await ops_test.model.applications["knative-serving"].set_config(
        {"registries-skipping-tag-resolving": custom_registries}
    )
    await ops_test.model.wait_for_idle(
        ["knative-serving"],
        status="active",
        raise_on_blocked=False,
        timeout=60 * 1,
    )

    # Assert
    client = lightkube.Client()
    config_deployment_cm = client.get(
        ConfigMap, "config-deployment", namespace=KNATIVE_SERVING_NAMESPACE
    )
    assert config_deployment_cm.data["registries-skipping-tag-resolving"] == custom_registries


async def test_config_features_node_selector_affinity_and_tolerations_enabled(ops_test: OpsTest):
    """
    Assert the feature flags in the KnativeServing CR for nodeselector, affinity, and tolerations
    are enabled in the `config-features` ConfigMap.
    """

    client = lightkube.Client()
    config_features_cm = client.get(
        ConfigMap, "config-features", namespace=KNATIVE_SERVING_NAMESPACE
    )
    assert config_features_cm.data["kubernetes.podspec-nodeselector"] == "enabled"
    assert config_features_cm.data["kubernetes.podspec-affinity"] == "enabled"
    assert config_features_cm.data["kubernetes.podspec-tolerations"] == "enabled"
