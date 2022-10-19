# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging

import pytest
import requests
import tenacity
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


# knative-operator is the charm that actually talks to prometheus
# to configure the OpenTelemetry collector to be scraped
APP_NAME = "knative-operator"


async def test_prometheus_grafana_integration(ops_test: OpsTest):
    """Deploy prometheus and required relations, then test the metrics."""
    prometheus = "prometheus-k8s"
    prometheus_scrape = "prometheus-scrape-config-k8s"
    scrape_config = {"scrape_interval": "30s"}

    # Deploy and relate prometheus
    await ops_test.model.deploy(prometheus, channel="latest/beta", trust=True)
    await ops_test.model.deploy(prometheus_scrape, channel="latest/beta", config=scrape_config)

    await ops_test.model.add_relation(APP_NAME, prometheus_scrape)
    await ops_test.model.add_relation(
        f"{APP_NAME}:otel-collector", "knative-eventing:otel-collector"
    )
    await ops_test.model.add_relation(
        f"{APP_NAME}:otel-collector", "knative-serving:otel-collector"
    )
    await ops_test.model.add_relation(
        f"{prometheus}:metrics-endpoint", f"{prometheus_scrape}:metrics-endpoint"
    )

    await ops_test.model.wait_for_idle(status="active", timeout=60 * 20)

    status = await ops_test.model.get_status()
    prometheus_unit_ip = status["applications"][prometheus]["units"][f"{prometheus}/0"]["address"]
    log.info(f"Prometheus available at http://{prometheus_unit_ip}:9090")

    for attempt in retry_for_5_attempts:
        log.info(
            f"Testing prometheus deployment (attempt " f"{attempt.retry_state.attempt_number})"
        )
        with attempt:
            r = requests.get(
                f"http://{prometheus_unit_ip}:9090/api/v1/query?"
                f'query=up{{juju_application="{APP_NAME}"}}'
            )
            response = json.loads(r.content.decode("utf-8"))
            response_status = response["status"]
            log.info(f"Response status is {response_status}")
            assert response_status == "success"

            response_metric = response["data"]["result"][0]["metric"]
            assert response_metric["juju_application"] == APP_NAME
            assert response_metric["juju_model"] == ops_test.model_name


# Helper to retry calling a function over 30 seconds or 5 attempts
retry_for_5_attempts = tenacity.Retrying(
    stop=(tenacity.stop_after_attempt(5) | tenacity.stop_after_delay(30)),
    wait=tenacity.wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
