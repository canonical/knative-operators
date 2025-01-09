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
from lightkube.resources.core_v1 import Service
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

EXPECTED_AFFINITY = "Affinity(nodeAffinity=NodeAffinity(preferredDuringSchedulingIgnoredDuringExecution=None, requiredDuringSchedulingIgnoredDuringExecution=NodeSelector(nodeSelectorTerms=[NodeSelectorTerm(matchExpressions=[NodeSelectorRequirement(key='disktype', operator='In', values=['ssd'])], matchFields=None)])), podAffinity=None, podAntiAffinity=None)"  # noqa E501
EXPECTED_TOLERATION = "Toleration(effect='NoSchedule', key='myTaint1', operator='Equal', tolerationSeconds=None, value='true')"  # noqa E501
EXPECTED_NODESELECTOR = {"myLabel1": "true"}

HELLOWORLD_EXAMPLE_IMAGE = yaml.safe_load(
    Path("./examples/helloworld-node-constraints.yaml").read_text()
)["spec"]["template"]["spec"]["containers"][0]["image"]

CLOUDEVENTS_MANIFEST = lightkube.codecs.load_all_yaml(
    Path("./examples/cloudevents-player.yaml").read_text()
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


@pytest.fixture()
def remove_helloworld_example(ops_test: OpsTest):
    """Fixture that attempts to remove the helloworld example after a test has run"""
    yield
    lightkube_client = Client()
    try:
        lightkube_client.delete(KSVC, "helloworld", namespace=ops_test.model_name)
    except ApiError as e:
        # If the ksvc doesn't exist, we can ignore the error
        if e.code == 404:
            log.info("Tried to delete helloworld knative service, but it didn't exist")
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
    lightkube_client = Client()

    for obj in CLOUDEVENTS_MANIFEST:
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
        idle_period=20,
    )

    # Assert that the activator image is trying to use the custom image.
    client = lightkube.Client()

    for attempt in RETRY_FOR_THREE_MINUTES:
        with attempt:
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

    for attempt in RETRY_FOR_THREE_MINUTES:
        with attempt:
            activator_deployment = client.get(
                Deployment, "activator", namespace=KNATIVE_SERVING_NAMESPACE
            )
            assert activator_deployment.spec.template.spec.containers[0].image == fake_image


async def test_ksvc_deployment_configs(ops_test: OpsTest, remove_helloworld_example):
    """
    Tests that the following configurations for KnativeServing work as expected:
    * progress-deadline
    * registries-skipping-tag-resolving
    * kubernetes.podspec-[affinity, nodeselector, tolerations] are enabled
    """

    # Act

    # Change the `progress-deadline` config
    custom_deadline = "123s"
    await ops_test.model.applications["knative-serving"].set_config(
        {"progress-deadline": custom_deadline}
    )

    # Configure KnativeServing to skip tag resolution for the registry where the helloworld
    # image is pulled
    await ops_test.model.applications["knative-serving"].set_config(
        {"registries-skipping-tag-resolving": "gcr.io"}
    )

    await ops_test.model.wait_for_idle(
        ["knative-serving"],
        status="active",
        raise_on_blocked=False,
        timeout=60 * 1,
    )

    # Create KSVC

    manifest = lightkube.codecs.load_all_yaml(
        Path("./examples/helloworld-node-constraints.yaml").read_text()
    )
    lightkube_client = Client()

    for obj in manifest:
        lightkube_client.create(obj, namespace=ops_test.model_name)

    # Get KSVC Deployment

    for attempt in RETRY_FOR_THREE_MINUTES:
        with attempt:
            deployment_list = lightkube_client.list(
                res=Deployment,
                namespace=ops_test.model_name,
                labels={"serving.knative.dev/service": "helloworld"},
            )
            ksvc_deployment = next(deployment_list)

    # Assert

    # Affinity
    assert str(ksvc_deployment.spec.template.spec.affinity) == EXPECTED_AFFINITY
    # Toleration
    assert str(ksvc_deployment.spec.template.spec.tolerations[0]) == EXPECTED_TOLERATION
    # NodeSelector
    assert ksvc_deployment.spec.template.spec.nodeSelector == EXPECTED_NODESELECTOR

    # ProgressDeadline
    assert (
        str(ksvc_deployment.spec.progressDeadlineSeconds) + "s" == custom_deadline
    )  # Concatenates the `s` for seconds to match the config

    # Assert tag is not resolved
    assert ksvc_deployment.spec.template.spec.containers[0].image == HELLOWORLD_EXAMPLE_IMAGE


@pytest_asyncio.fixture
async def restore_queue_sidecar_image_setting(ops_test: OpsTest):
    """
    Saves the current queue_sidecar_image setting for serving.
    Restores it after test completes.
    """
    queue_sidecar_image_config = (
        await ops_test.model.applications["knative-serving"].get_config()
    )["queue_sidecar_image"]["value"]

    yield
    await ops_test.model.applications["knative-serving"].set_config(
        {"queue_sidecar_image": queue_sidecar_image_config}
    )

    await ops_test.model.wait_for_idle(
        ["knative-serving"],
        status="active",
        raise_on_blocked=False,
        timeout=60 * 1,
    )


async def test_queue_sidecar_image_config(
    ops_test: OpsTest, restore_queue_sidecar_image_setting, remove_cloudevents_player_example
):
    """
    Changes `queue_sidecar_image` config and checks that the Knative Service is trying to use it
    as the image for `queue-proxy` container
    """
    fake_image = "not-a-real-image"

    # Act
    await ops_test.model.applications["knative-serving"].set_config(
        {"queue_sidecar_image": fake_image}
    )

    await ops_test.model.wait_for_idle(
        ["knative-serving"],
        status="active",
        raise_on_blocked=False,
        timeout=60 * 1,
    )

    # Create a Knative Service
    client = Client()

    for obj in CLOUDEVENTS_MANIFEST:
        client.create(obj, namespace=ops_test.model_name)

    # Wait for the Deployment to get created
    for attempt in RETRY_FOR_THREE_MINUTES:
        with attempt:
            cloudevents_deployment = client.get(
                Deployment, "cloudevents-player-00001-deployment", namespace=ops_test.model_name
            )

    # Assert that the Knative Service is trying to use the custom image.
    assert cloudevents_deployment.spec.template.spec.containers[1].image == fake_image


async def test_serving_proxy_config(ops_test: OpsTest):
    """
    Changes `http-proxy`, `https-proxy` and `no-proxy` configs and checks that the Knative Serving
    controller container is using the values from configs as environment variables.
    """

    # Act
    test_http_proxy = "my_http_proxy"
    test_https_proxy = "my_https_proxy"
    test_no_proxy = "no_proxy"

    await ops_test.model.applications["knative-serving"].set_config(
        {"http-proxy": test_http_proxy, "https-proxy": test_https_proxy, "no-proxy": test_no_proxy}
    )

    await ops_test.model.wait_for_idle(
        ["knative-serving"],
        status="active",
        raise_on_blocked=False,
        timeout=60 * 1,
    )

    client = Client()

    for attempt in RETRY_FOR_THREE_MINUTES:
        with attempt:
            # Get Knative Serving controller Deployment
            controller_deployment = client.get(
                Deployment, "controller", namespace=KNATIVE_SERVING_NAMESPACE
            )

            # Get Knative Serving controller environment variables
            serving_controller_env_vars = controller_deployment.spec.template.spec.containers[
                0
            ].env

            http_proxy_env = https_proxy_env = no_proxy_env = None

            # Get proxy environment variables from all Knative Serving controller env vars
            for env_var in serving_controller_env_vars:
                if env_var.name == "HTTP_PROXY":
                    http_proxy_env = env_var.value
                elif env_var.name == "HTTPS_PROXY":
                    https_proxy_env = env_var.value
                elif env_var.name == "NO_PROXY":
                    no_proxy_env = env_var.value

            # Assert Deployment spec contains correct proxy environment variables
            assert http_proxy_env == test_http_proxy
            assert https_proxy_env == test_https_proxy
            assert no_proxy_env == test_no_proxy
