# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from charmed_kubeflow_chisme.testing import (
    assert_alert_rules,
    assert_logging,
    assert_metrics_endpoint,
    deploy_and_assert_grafana_agent,
    get_alert_rules,
)
from lightkube import Client
from lightkube.resources.core_v1 import Namespace
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_delay, wait_fixed

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_ROOT = "."
APP_NAME = "knative-operator"

log = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_build_and_deploy_with_relations(ops_test: OpsTest, request):
    # Build and deploy charm from local source folder or use
    # a charm artefact passed using --charm-path
    entity_url = (
        await ops_test.build_charm(".")
        if not (entity_url := request.config.getoption("--charm-path"))
        else entity_url
    )

    image_path = METADATA["resources"]["knative-operator-image"]["upstream-source"]
    webhook_image_path = METADATA["resources"]["knative-operator-webhook-image"]["upstream-source"]
    resources = {
        "knative-operator-image": image_path,
        "knative-operator-webhook-image": webhook_image_path,
    }

    await ops_test.model.deploy(
        entity_url=entity_url, application_name=APP_NAME, resources=resources, trust=True
    )

    await ops_test.model.wait_for_idle(
        status="active",
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=60 * 10,
    )

    # Deploying grafana-agent-k8s and add all relations
    await deploy_and_assert_grafana_agent(
        ops_test.model, APP_NAME, metrics=True, logging=True, dashboard=False
    )


async def test_logging(ops_test):
    """Test logging is defined in relation data bag."""
    app = ops_test.model.applications[APP_NAME]
    await assert_logging(app)


async def test_metrics_enpoint(ops_test):
    """Test metrics_endpoints are defined in relation data bag and their accessibility.

    This function gets all the metrics_endpoints from the relation data bag, checks if
    they are available in current defined targets in Grafana agent.
    """
    app = ops_test.model.applications[APP_NAME]
    # Note(rgildein): Without otel-collector relation we will not see otel as terget.
    await assert_metrics_endpoint(app, metrics_port=9090, metrics_path="/metrics")


async def test_alert_rules(ops_test):
    """Test check charm alert rules and rules defined in relation data bag."""
    app = ops_test.model.applications[APP_NAME]
    alert_rules = get_alert_rules()
    log.info("found alert_rules: %s", alert_rules)
    await assert_alert_rules(app, alert_rules)


RETRY_FOR_TWO_MINUTES = Retrying(
    stop=stop_after_delay(60 * 2),
    wait=wait_fixed(5),
    reraise=True,
)


async def test_scale_down_app_namespace_unaffected(ops_test):
    """
    Test scaling down the application to 0 does not affect the namespace.
    """

    # Scale down to 0
    await ops_test.model.applications["knative-operator"].scale(scale=0)

    # Wait until scale down takes effect
    for attempt in RETRY_FOR_TWO_MINUTES:
        with attempt:

            # Get application status
            model_status = await ops_test.model.get_status()
            app_status = model_status.applications["knative-operator"].status["status"]

            # Get number of units
            num_units = len(model_status.applications["knative-operator"].units)

            log.info(
                f"Waiting for application to scale down, status is {app_status}, Number of units is {num_units}"
            )

            # Assert the status is unknown and number of units is 0
            # This is the expected state when the application is scaled down to 0
            assert app_status == "unknown"
            assert num_units == 0

    client = Client()

    # Get the status of the test namespace
    namespace = client.get(res=Namespace, name=ops_test.model_name)
    namespace_status = namespace.status.phase

    # Assert namespace is Active
    assert (
        namespace_status == "Active"
    ), f"Expected namespace to be 'Active', but got '{namespace_status}'"
