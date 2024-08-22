# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import logging

import pytest
from charmed_kubeflow_chisme.testing import (
    assert_logging,
    assert_metrics_endpoint,
    deploy_and_assert_grafana_agent,
)
from pytest_operator.plugin import OpsTest
from test_bundle import KNATIVE_OPERATOR_RESOURCES

log = logging.getLogger(__name__)

# knative-operator is the charm that actually talks to prometheus
# to configure the OpenTelemetry collector to be scraped
APP_NAME = "knative-operator"


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_build_deploy_knative_charms(ops_test: OpsTest):
    # Build knative charms
    charms_path = "./charms/knative"
    knative_charms = await ops_test.build_charms(
        f"{charms_path}-operator", f"{charms_path}-serving", f"{charms_path}-eventing"
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
        timeout=120 * 10,
    )

    await ops_test.model.deploy(
        knative_charms["knative-serving"],
        application_name="knative-serving",
        config={
            "namespace": f"{ops_test.model_name}-serving",
            "istio.gateway.namespace": ops_test.model_name,
        },
        trust=True,
    )

    await ops_test.model.deploy(
        knative_charms["knative-eventing"],
        application_name="knative-eventing",
        config={"namespace": f"{ops_test.model_name}-eventing"},
        trust=True,
    )

    # Wait here (by using idle_period=60) to avoid a race condition between the rest
    # of the tests and knative eventing/serving coming up. This race condition is
    # because of: https://github.com/canonical/knative-operators/issues/50
    await ops_test.model.wait_for_idle(
        status="active", raise_on_blocked=False, timeout=60 * 10, idle_period=60
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
    await assert_metrics_endpoint(app, metrics_port=9090, metrics_path="/metrics")

    # Add otel-coolector relation, which will deploy the OpenTelemetry collector
    await ops_test.model.integrate(f"{APP_NAME}:otel-collector", "knative-eventing:otel-collector")
    await ops_test.model.integrate(f"{APP_NAME}:otel-collector", "knative-serving:otel-collector")
    await ops_test.model.wait_for_idle(raise_on_blocked=False, timeout=60 * 5, idle_period=60)

    await assert_metrics_endpoint(app, metrics_port=8889, metrics_path="/metrics")
