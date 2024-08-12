# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from charmed_kubeflow_chisme.testing import (
    assert_logging,
    assert_metrics_endpoint,
    deploy_and_assert_grafana_agent,
)
from pytest_operator.plugin import OpsTest

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_ROOT = "."
APP_NAME = "knative-operator"

log = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_build_and_deploy_with_relations(ops_test: OpsTest):
    built_charm_path = await ops_test.build_charm(CHARM_ROOT)
    log.info(f"Built charm {built_charm_path}")

    image_path = METADATA["resources"]["knative-operator-image"]["upstream-source"]
    webhook_image_path = METADATA["resources"]["knative-operator-webhook-image"]["upstream-source"]
    resources = {
        "knative-operator-image": image_path,
        "knative-operator-webhook-image": webhook_image_path,
    }

    await ops_test.model.deploy(
        entity_url=built_charm_path, application_name=APP_NAME, resources=resources, trust=True
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
