#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock

import pytest
from lightkube.core.exceptions import ApiError
from ops.model import ActiveStatus, BlockedStatus
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
def mocked_client(mocker):
    """Yields a mocked lightkube Client."""
    mocked_lightkube_client = MagicMock()
    mocked_lightkube_client_factory = mocker.patch("charm.Client")
    mocked_lightkube_client_factory.return_value = mocked_lightkube_client
    yield mocked_lightkube_client


def test_events(harness, mocked_client, mocker):
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


def test_apply_all_resources(harness, mocked_client, mocked_codecs, mocker):
    harness.begin()
    # Trigger _main event handler that calls _apply_all_resources
    harness.charm.on.install.emit()
    mocked_codecs.load_all_yaml.assert_called()

    mocked_client.apply.side_effect = _FakeApiError()
    try:
        harness.charm.on.install.emit()
    except ApiError:
        assert harness.model.unit.status == BlockedStatus(
            f"Applying resources failed with code {mocked_client.apply.side_effect.response.code}."
        )


def test_update_layer(harness, mocked_client, mocker):
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
