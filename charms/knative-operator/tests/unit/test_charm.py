#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, patch

import pytest
from lightkube.core.exceptions import ApiError
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus
from ops.testing import Harness

from charm import KnativeOperatorCharm


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
    """Yields a mocked lightkube Client."""
    mocked_resource_handler = MagicMock()
    mocked_resource_handler_factory = mocker.patch("charm.KRH")
    mocked_resource_handler_factory.return_value = mocked_resource_handler
    yield mocked_resource_handler


@pytest.fixture()
def mocked_container_replan(mocker):
    yield mocker.patch("ops.model.Container.replan")


def test_events(harness, mocked_resource_handler, mocker):
    harness.begin()
    main = mocker.patch("charm.KnativeOperatorCharm._main")
    pebble_ready = mocker.patch("charm.KnativeOperatorCharm._on_knative_operator_pebble_ready")

    harness.charm.on.install.emit()
    main.assert_called_once()
    main.reset_mock()

    harness.charm.on.config_changed.emit()
    main.assert_called_once()
    main.reset_mock()

    harness.charm.on.knative_operator_pebble_ready.emit("knative-operator")
    pebble_ready.assert_called_once()
    pebble_ready.reset_mock()


def test_apply_all_resources_active(harness, mocked_resource_handler):
    harness.begin()
    harness.charm._apply_all_resources()
    mocked_resource_handler.apply.assert_called()
    assert harness.model.unit.status == ActiveStatus()


def test_apply_all_resource_exception(harness, mocked_resource_handler):
    harness.begin()
    mocked_resource_handler.apply.side_effect = _FakeApiError()
    harness.charm._apply_all_resources()
    assert harness.model.unit.status == BlockedStatus(
        f"ApiError: {mocked_resource_handler.apply.side_effect.response.code}"
    )


def test_update_layer_active(harness, mocked_resource_handler, mocker):
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
                    "CONFIG_LOGGING_NAME": "config-loggig",
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


@patch("charm.KRH")
@patch("charm.delete_many")
def test_on_remove_success(
    delete_many: MagicMock,
    _: MagicMock,
    harness,
):
    harness.begin()
    harness.charm.on.remove.emit()
    delete_many.assert_called()
    assert isinstance(harness.charm.model.unit.status, MaintenanceStatus)


@patch("charm.KRH")
@patch("charm.delete_many")
def test_on_remove_failure(
    delete_many: MagicMock,
    _: MagicMock,
    harness,
):
    harness.begin()
    delete_many.side_effect = _FakeApiError()
    with pytest.raises(ApiError):
        harness.charm.on.remove.emit()
