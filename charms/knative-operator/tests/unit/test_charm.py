#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import datetime
from unittest.mock import MagicMock

import pytest
from lightkube.core.exceptions import ApiError
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Pod
from ops.model import ActiveStatus, BlockedStatus
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
def mocked_client(mocker):
    """Yields a mocked lightkube Client."""
    mocked_lightkube_client = MagicMock()
    mocked_lightkube_client_factory = mocker.patch("charm.Client")
    mocked_lightkube_client_factory.return_value = mocked_lightkube_client
    yield mocked_lightkube_client


@pytest.fixture()
def mocked_codecs_load_all_yaml(mocked_codecs, mocker):
    mocker.patch("charm.KnativeOperatorCharm._update_layer")
    pod_names = ["a", "b"]
    resources = [Pod(kind="Pod", metadata=ObjectMeta(name=str(name))) for name in pod_names]
    mocked_codecs.load_all_yaml.return_value = resources


@pytest.fixture()
def mocked_container_replan(mocker):
    yield mocker.patch("ops.model.Container.replan")


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


def test_apply_all_resources_active(
    harness, mocked_client, mocked_codecs, mocked_codecs_load_all_yaml
):
    harness.begin()
    harness.charm._apply_all_resources()
    mocked_codecs.load_all_yaml.assert_called()
    mocked_client.apply.assert_called()
    assert harness.model.unit.status == ActiveStatus()


def test_apply_all_resource_exception(harness, mocked_client, mocked_codecs_load_all_yaml):
    harness.begin()
    mocked_client.apply.side_effect = _FakeApiError()
    with pytest.raises(ApiError):
        harness.charm._apply_all_resources()
    assert harness.model.unit.status == BlockedStatus(
        f"Applying resources failed with code {mocked_client.apply.side_effect.response.code}."
    )


def test_update_layer_active(harness, mocked_client, mocker):
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


def test_update_layer_exception(harness, mocked_client, mocked_container_replan):
    harness.begin()
    mocked_container_replan.side_effect = _FakeChangeError()
    mocked_event = MagicMock()
    with pytest.raises(ChangeError):
        harness.charm._update_layer(mocked_event)
    assert harness.model.unit.status == BlockedStatus("Failed to replan")
