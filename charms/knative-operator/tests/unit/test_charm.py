#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import datetime
from contextlib import nullcontext as does_not_raise
from unittest.mock import MagicMock, patch

import pytest
from lightkube.core.exceptions import ApiError
from lightkube.models.core_v1 import ServiceSpec
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Service
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus
from ops.pebble import Change, ChangeError, ChangeID
from ops.testing import Harness
from tenacity import Retrying, stop_after_attempt

from charm import (
    KNATIVE_OPERATOR,
    KNATIVE_OPERATOR_WEBHOOK,
    REQUIRED_CONFIGMAPS,
    REQUIRED_SECRETS,
    KnativeOperatorCharm,
    wait_for_required_kubernetes_resources,
)


class _FakeChange:
    def __init__(self):
        self.cid = ChangeID("0")
        self.spawn_time = datetime.datetime.now()
        self.change = Change(
            self.cid, "kind", "summary", "status", [], False, None, self.spawn_time, None
        )


class _FakeChangeError(ChangeError):
    def __init__(self):
        super().__init__("err", change=_FakeChange())


class _FakeResponse:
    """Used to fake an httpx response during testing only."""

    def __init__(self, code):
        self.code = code

    def json(self):
        return {"apiVersion": 1, "code": self.code, "message": "broken"}


class _FakeApiError(ApiError):
    """Used to simulate an ApiError during testing."""

    def __init__(self, code=400):
        super().__init__(response=_FakeResponse(code))


@pytest.fixture
def harness():
    """Returns a harnessed charm with leader == True."""
    harness = Harness(KnativeOperatorCharm)
    harness.set_leader(True)
    return harness


@pytest.fixture()
def mocked_codecs(mocker):
    """Yields a mocked lightkube codecs."""
    yield mocker.patch("charm.codecs")


@pytest.fixture()
def mocked_resource_handler(mocker):
    """Yields a mocked resource handler."""
    mocked_resource_handler = MagicMock()
    mocked_resource_handler_factory = mocker.patch("charm.KRH")
    mocked_resource_handler_factory.return_value = mocked_resource_handler
    yield mocked_resource_handler


@pytest.fixture()
def mocked_lightkube_client(mocker, mocked_resource_handler):
    """Prevents lightkube clients from being created, returning a mock instead."""
    mocked_resource_handler.lightkube_client = MagicMock()
    yield mocked_resource_handler.lightkube_client


@pytest.fixture()
def mocked_container_replan(mocker):
    yield mocker.patch("ops.model.Container.replan")


@pytest.fixture()
def mocked_metrics_endpoint_provider(mocker):
    """Yields a mocked MetricsEndpointProvider."""
    yield mocker.patch("charm.MetricsEndpointProvider")


def test_log_forwarding(harness, mocked_resource_handler, mocked_metrics_endpoint_provider):
    with patch("charm.LogForwarder") as mock_logging:
        harness.begin()
        mock_logging.assert_called_once_with(charm=harness.charm)


def test_events(harness, mocked_resource_handler, mocked_metrics_endpoint_provider, mocker):
    harness.begin()
    main = mocker.patch("charm.KnativeOperatorCharm._main")
    otel_relation_created = mocker.patch(
        "charm.KnativeOperatorCharm._on_otel_collector_relation_created"
    )

    harness.charm.on.install.emit()
    main.assert_called_once()
    main.reset_mock()

    harness.charm.on.config_changed.emit()
    main.assert_called_once()
    main.reset_mock()

    harness.charm.on.knative_operator_pebble_ready.emit("knative-operator")
    main.assert_called_once()
    main.reset_mock()

    harness.charm.on.knative_operator_webhook_pebble_ready.emit("knative-operator-webhook")
    main.assert_called_once()
    main.reset_mock()

    rel_id = harness.add_relation("otel-collector", "app")
    harness.update_relation_data(rel_id, "app", {"some-key": "some-value"})
    otel_relation_created.assert_called_once()


def test_apply_resources_active(
    harness, mocked_resource_handler, mocked_metrics_endpoint_provider
):
    harness.begin()
    harness.charm._apply_resources(mocked_resource_handler)
    mocked_resource_handler.apply.assert_called()
    assert harness.model.unit.status == ActiveStatus()


def test_apply_resources_exception(
    harness, mocked_resource_handler, mocked_metrics_endpoint_provider
):
    harness.begin()
    mocked_resource_handler.apply.side_effect = _FakeApiError()
    harness.charm._apply_resources(mocked_resource_handler)
    assert harness.model.unit.status == BlockedStatus(
        f"ApiError: {mocked_resource_handler.apply.side_effect.response.code}"
    )


@pytest.mark.parametrize(
    "container_name",
    [
        "knative-operator",
        "knative-operator-webhook",
    ],
)
def test_update_layer_active(
    container_name, harness, mocked_resource_handler, mocker, mocked_metrics_endpoint_provider
):
    # The charm uses a service name that is the same as the container name
    service_name = container_name

    mocker.patch("charm.wait_for_required_kubernetes_resources")

    harness.begin_with_initial_hooks()

    # Check the layer gets created
    harness_events = {
        KNATIVE_OPERATOR: harness.charm.on.knative_operator_pebble_ready,
        KNATIVE_OPERATOR_WEBHOOK: harness.charm.on.knative_operator_webhook_pebble_ready,
    }
    harness_events[container_name].emit(container_name)
    assert harness.get_container_pebble_plan(container_name)._services is not None

    # TODO: This could be extracted and made cleaner
    expected_plan = {}
    if container_name == "knative-operator":
        expected_plan = {
            "services": {
                service_name: {
                    "summary": "entrypoint of the knative-operator image",
                    "startup": "enabled",
                    "override": "replace",
                    "command": "/ko-app/operator",
                    "environment": {
                        "POD_NAME": harness.model.app.name,
                        "SYSTEM_NAMESPACE": harness.model.name,
                        "METRICS_DOMAIN": "knative.dev/operator",
                        "CONFIG_LOGGING_NAME": "config-logging",
                        "CONFIG_OBSERVABILITY_NAME": "config-observability",
                    },
                }
            },
        }
    elif container_name == "knative-operator-webhook":
        expected_plan = {
            "services": {
                service_name: {
                    "summary": "entrypoint of the knative-operator-webhook image",
                    "startup": "enabled",
                    "override": "replace",
                    "command": "/ko-app/webhook",
                    "environment": {
                        "POD_NAME": harness.model.app.name,
                        "SYSTEM_NAMESPACE": harness.model.name,
                        "METRICS_DOMAIN": "knative.dev/operator",
                        "CONFIG_LOGGING_NAME": "config-logging",
                        "CONFIG_OBSERVABILITY_NAME": "config-observability",
                        "WEBHOOK_NAME": "operator-webhook",
                        "WEBHOOK_PORT": "8443",
                    },
                }
            },
        }
    updated_plan = harness.get_container_pebble_plan(container_name).to_dict()
    assert expected_plan == updated_plan

    service = harness.model.unit.get_container(container_name).get_service(service_name)
    assert service.is_running() is True

    assert harness.model.unit.status == ActiveStatus()


@pytest.mark.parametrize(
    "container_name",
    [
        "knative-operator",
        "knative-operator-webhook",
    ],
)
@patch("charm.wait_for_required_kubernetes_resources", lambda *args, **kwargs: None)
def test_update_layer_exception(
    container_name,
    harness,
    mocked_resource_handler,
    mocked_container_replan,
    mocked_metrics_endpoint_provider,
):
    harness.begin()
    mocked_container_replan.side_effect = _FakeChangeError()
    mocked_event = MagicMock()
    harness.set_can_connect(container_name, True)
    with pytest.raises(ChangeError):
        harness.charm._update_layer(mocked_event, container_name)
    assert harness.model.unit.status == BlockedStatus(f"Failed to replan for {container_name}")


def test_otel_exporter_ip_on_404_apierror(
    mocker, harness, mocked_lightkube_client, mocked_metrics_endpoint_provider
):
    mocked_lightkube_client.get.side_effect = _FakeApiError(404)
    mocked_logger = mocker.patch("charm.logger")
    harness.begin()
    ip = harness.charm._otel_exporter_ip
    mocked_logger.info.assert_called_with(
        "The OpenTelemetry Collector may not be deployed yet.This may be temporary or due to a missing otel-collector relation."  # noqa: E501
    )
    assert ip is None


def test_otel_exporter_ip_on_any_apierror(
    mocker, harness, mocked_lightkube_client, mocked_metrics_endpoint_provider
):
    mocked_logger = mocker.patch("charm.logger")
    mocked_lightkube_client.get.side_effect = _FakeApiError()
    with pytest.raises(ApiError):
        harness.begin()
        mocked_logger.error.assert_called_with(
            "Something went wrong trying to get the OpenTelemetry Collector"
        )


def test_otel_exporter_ip_success(
    harness, mocked_lightkube_client, mocked_metrics_endpoint_provider
):
    expected_ip = "10.10.10.10"
    dummy_service = Service(
        apiVersion="v1",
        kind="Service",
        metadata=ObjectMeta(name="otel-exporter", namespace=harness.model.name),
        spec=ServiceSpec(clusterIP=f"{expected_ip}"),
    )
    mocked_lightkube_client.get.return_value = dummy_service
    harness.begin()
    with does_not_raise():
        ip = harness.charm._otel_exporter_ip
    assert ip == expected_ip


def test_relation_created_databag(
    mocker, harness, mocked_metrics_endpoint_provider, mocked_lightkube_client
):
    harness.set_model_name(name="my-model")
    harness.begin()
    mocked_otel_exporter_ip = mocker.patch("charm.KnativeOperatorCharm._otel_exporter_ip")
    mocked_otel_exporter_ip.return_value = "10.10.10.10"
    expected_relation_data = {
        "otel_collector_svc_namespace": harness.model.name,
        "otel_collector_svc_name": "otel-collector",
        "otel_collector_port": "55678",
    }
    rel_id = harness.add_relation("otel-collector", "app")
    actual_relation_data = harness.get_relation_data(rel_id, harness.charm.app.name)
    assert expected_relation_data == actual_relation_data
    assert harness.model.unit.status == ActiveStatus()


@patch("charm.KRH")
@patch("charm.delete_many")
def test_on_remove_success(
    delete_many: MagicMock, _: MagicMock, harness, mocked_metrics_endpoint_provider
):
    harness.begin()
    harness.charm.on.remove.emit()
    delete_many.assert_called()
    assert isinstance(harness.charm.model.unit.status, MaintenanceStatus)


@patch("charm.KRH")
@patch("charm.delete_many")
def test_on_remove_failure(
    delete_many: MagicMock, _: MagicMock, harness, mocked_metrics_endpoint_provider
):
    harness.begin()
    delete_many.side_effect = _FakeApiError()
    with pytest.raises(ApiError):
        harness.charm.on.remove.emit()


@pytest.fixture()
def mocked_lightkube_base_client(mocker):
    """Mocks the actual Lightkube Client class rather than the resource handler's Client."""
    mocked_lightkube_client = MagicMock()
    mocked_lightkube_client_class = mocker.patch("charm.Client")
    mocked_lightkube_client_class.return_value = mocked_lightkube_client
    yield mocked_lightkube_client


def test_wait_for_required_kubernetes_resources_success(mocked_lightkube_base_client):
    """Tests case where resources do exist after some time.

    Given an environment that will eventually (after a few tries) have the required resources,
    assert that the function returns successfully
    """
    mocked_lightkube_client = mocked_lightkube_base_client

    # Lightkube will fail the first 3 access, then return successfully after
    mocked_lightkube_client.get.side_effect = [
        _FakeApiError(404),
        _FakeApiError(404),
        _FakeApiError(404),
        None,
        None,
        None,
    ]

    retryer = Retrying(
        stop=stop_after_attempt(15),
        reraise=True,
    )

    wait_for_required_kubernetes_resources("", retryer=retryer)

    # Assert we had 3 attempts end in a failure after one get, and then a 4th attempt that had
    # 3 successful returns
    assert mocked_lightkube_client.get.call_count == 6

    # Assert that the last 3 calls of .get attempted to get the required resources
    required_resource_names = REQUIRED_CONFIGMAPS + REQUIRED_SECRETS

    # call_args_list returns a list of Call objects, each of which are a tuple of (args, kwargs).
    # We assert that the kwargs has the correct resource name.
    requested_resource_names = [
        kwargs["name"] for (_, kwargs) in mocked_lightkube_client.get.call_args_list[-3:]
    ]
    for name in required_resource_names:
        assert name in requested_resource_names


def test_wait_for_required_kubernetes_failure(mocked_lightkube_base_client):
    """Tests case where resources do not exist and the wait should raise an exception.

    Given an environment that will never have the required resources,
    assert that the function raises after the expected number of attempts.
    """
    mocked_lightkube_client = mocked_lightkube_base_client

    # Lightkube's Client.get will always raise an exception
    mocked_lightkube_client.get.side_effect = _FakeApiError(404)

    n_attempts = 3
    retryer = Retrying(
        stop=stop_after_attempt(n_attempts),
        reraise=True,
    )

    with pytest.raises(ApiError):
        wait_for_required_kubernetes_resources("", retryer=retryer)

    # Assert we had 3 attempts end in a failure after one get, and then a 4th attempt that had
    # 3 successful returns
    assert mocked_lightkube_client.get.call_count == n_attempts
