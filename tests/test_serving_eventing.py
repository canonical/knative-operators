import json
import logging

import pytest
import requests
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_attempt, stop_after_delay, wait_exponential

logger = logging.getLogger(__name__)

CHARMS_PATH = "./operators"


@pytest.mark.abort_on_fail
async def test_build_and_deploy_serving(ops_test: OpsTest):
    knative_controller_charm = "knative-controller"
    built_charm_path = await ops_test.build_charm(f"{CHARMS_PATH}/{knative_controller_charm}")
    logger.info(f"Built charm {built_charm_path}")

    await ops_test.model.deploy(
        entity_url=built_charm_path,
        application_name=knative_controller_charm,
        trust=True,
    )

    logger.info("Deploying istio bundle")
    await ops_test.model.deploy(
        entity_url="istio-pilot",
        channel="latest/edge",
        config={'default-gateway': 'knative-ingress-gateway'},
        trust=True,
    )
    await ops_test.model.deploy(
        entity_url="istio-gateway",
        channel="latest/edge",
        config={'kind': 'ingress'},
        trust=True,
    )
    await ops_test.model.add_relation("istio-pilot:istio-pilot", "istio-gateway:istio-pilot")

    logger.info("Deploying the knative serving charms")
    for charm in [
        "knative-istio-controller",
        "knative-activator",
        "knative-autoscaler",
        "knative-webhook"
    ]:
        built_charm_path = await ops_test.build_charm(f"{CHARMS_PATH}/{charm}")
        logger.info(f"Built charm {built_charm_path}")
        await ops_test.model.deploy(
            entity_url=built_charm_path,
            application_name=charm,
            trust=True,
        )

    await ops_test.model.wait_for_idle(
        status="active",
        raise_on_blocked=True,
        timeout=60 * 10,
    )
    logger.info("Knative and istio bundles deployed. Proceeding to test knative serving")


async def wait_for_pods_ready(ops_test: OpsTest):
    """A helper to wait for the pods to be created"""
    await ops_test.run(
        "kubectl",
        "wait",
        "--for=condition=ready",
        "pods",
        "-n",
        ops_test.model_name,
        "-l",
        "app=hello-world",
        "--timeout=2m")


async def test_serving(ops_test: OpsTest):
    """Tests if knative serving works properly.

    Deploys an example Hello World app, tests its response
    and ensures that the pods get created.
    """
    await ops_test.run("kubectl", "apply", "-f", "tests/hello.yaml", "-n", ops_test.model_name, check=True)
    await wait_for_pods_ready(ops_test)
    hello_ksvc = await ops_test.run("kubectl", "get", "ksvc/hello", "-n", ops_test.model_name, "-o", "json")

    hello_ksvc_obj = json.loads(hello_ksvc[1])
    hello_ksvc_url = hello_ksvc_obj["status"]["url"]
    logger.info(f"App available at {hello_ksvc_url}")

    for attempt in retry_for_5_attempts:
        logger.info(
            f"Testing hello app deployment (attempt "
            f"{attempt.retry_state.attempt_number})"
        )
        with attempt:
            r = requests.get(hello_ksvc_url)
            # Wait for knative to run the deployment
            await wait_for_pods_ready(ops_test)

            assert r.status_code == 200
            assert r.text == "Hello World!\n"


@pytest.mark.abort_on_fail
async def test_build_and_deploy_eventing(ops_test: OpsTest):
    """Deploy the knative-eventing charms.

    NOTE: These 2 charms are deployed in a separate test purposely.
    Once the issue described in https://github.com/canonical/knative-operators/pull/5
    is fixed, they could be deployed in a bundle with serving charms.
    """
    logger.info("Deploying the knative eventing charms")
    for charm in [
        "knative-eventing-controller",
        "knative-eventing-webhook"
    ]:
        built_charm_path = await ops_test.build_charm(f"{CHARMS_PATH}/{charm}")
        logger.info(f"Built charm {built_charm_path}")
        await ops_test.model.deploy(
            entity_url=built_charm_path,
            application_name=charm,
            trust=True,
        )

    await ops_test.model.wait_for_idle(
        status="active",
        raise_on_blocked=True,
        timeout=60 * 10,
    )


async def test_eventing(ops_test: OpsTest):
    await ops_test.run(
        "kubectl",
        "wait",
        "--for=condition=ready",
        "pods",
        "--all",
        "-n",
        ops_test.model_name,
        "--timeout=5m",
        check=True,
    )

    await ops_test.run(
        "kubectl",
        "wait",
        "--for=condition=available",
        "deployments",
        "--all",
        "-n",
        ops_test.model_name,
        "--timeout=5m",
        check=True,
    )
    # TODO: Expand the tests as per https://github.com/Barteus/kubeflow-examples/tree/main/knative-example


# Helper to retry calling a function over 60 seconds or 5 attempts
retry_for_5_attempts = Retrying(
    stop=(stop_after_attempt(5) | stop_after_delay(60)),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
