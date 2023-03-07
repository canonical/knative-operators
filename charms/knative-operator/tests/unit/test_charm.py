#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
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

from charm import KnativeOperatorCharm


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


def test_events(harness, mocked_resource_handler, mocked_metrics_endpoint_provider, mocker):
    harness.begin()
    main = mocker.patch("charm.KnativeOperatorCharm._main")
    pebble_ready = mocker.patch("charm.KnativeOperatorCharm._on_knative_operator_pebble_ready")
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
    pebble_ready.assert_called_once()
    pebble_ready.reset_mock()

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


def test_update_layer_active(
    harness, mocked_resource_handler, mocker, mocked_metrics_endpoint_provider
):
    harness.begin()
    # Check the initial Pebble plan is empty
    initial_plan = harness.get_container_pebble_plan("knative-operator")
    assert initial_plan.to_yaml() == "{}\n"

    # Check the layer gets created
    harness.charm.on.knative_operator_pebble_ready.emit("knative-operator")
    assert harness.get_container_pebble_plan("knative-operator")._services is not None

    expected_plan = {
        "services": {
            "/ko-app/operator": {
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
    updated_plan = harness.get_container_pebble_plan("knative-operator").to_dict()
    assert expected_plan == updated_plan

    service = harness.model.unit.get_container("knative-operator").get_service("/ko-app/operator")
    assert service.is_running() is True

    assert harness.model.unit.status == ActiveStatus()


def test_update_layer_exception(
    harness, mocked_resource_handler, mocked_container_replan, mocked_metrics_endpoint_provider
):
    harness.begin()
    mocked_container_replan.side_effect = _FakeChangeError()
    mocked_event = MagicMock()
    with pytest.raises(ChangeError):
        harness.charm._update_layer_knative_operator(mocked_event)
    assert harness.model.unit.status == BlockedStatus("Failed to replan")


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
