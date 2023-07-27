# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
from contextlib import nullcontext as does_not_raise
from unittest.mock import MagicMock, patch

import pytest
from charmed_kubeflow_chisme.lightkube.mocking import FakeApiError
from lightkube import ApiError
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus


class _FakeResponse:
    """Used to fake an httpx response during testing only."""

    def __init__(self, code):
        self.code = code
        self.name = ""

    def json(self):
        reason = ""
        if self.code == 409:
            reason = "AlreadyExists"
        return {
            "apiVersion": 1,
            "code": self.code,
            "message": "broken",
            "reason": reason,
        }


class _FakeApiError(ApiError):
    """Used to simulate an ApiError during testing."""

    def __init__(self, code=400):
        super().__init__(response=_FakeResponse(code))


def test_events(harness, mocked_lightkube_client):
    # Test install and config_changed event handlers are called
    harness.begin()
    harness.charm._on_install = MagicMock()
    harness.charm._on_config_changed = MagicMock()
    harness.charm._on_otel_collector_relation_changed = MagicMock()

    harness.charm.on.install.emit()
    harness.charm._on_install.assert_called_once()

    harness.charm.on.config_changed.emit()
    harness.charm._on_config_changed.assert_called_once()

    rel_id = harness.add_relation("otel-collector", "app")
    harness.update_relation_data(rel_id, "app", {"some-key": "some-value"})
    harness.charm._on_otel_collector_relation_changed.assert_called_once()


def test_on_install_active(harness, mocked_lightkube_client):
    harness.begin()
    harness.update_config({"namespace": "test"})
    harness.charm.resource_handler.apply = MagicMock()
    harness.charm.resource_handler.apply.return_value = None
    harness.charm.on.install.emit()
    assert harness.model.unit.status == ActiveStatus()


@pytest.mark.parametrize(
    "apply_error, raised_exception",
    (
        (FakeApiError(400), pytest.raises(FakeApiError)),
        (
            FakeApiError(403),
            pytest.raises(FakeApiError),
        ),
    ),
)
def test_apply_and_set_status_blocked(
    apply_error,
    raised_exception,
    harness,
    mocked_lightkube_client,
    mocker,
):
    harness.begin()
    harness.charm.resource_handler.apply = MagicMock()
    harness.charm.resource_handler.apply.side_effect = apply_error

    harness.charm._apply_and_set_status()
    with raised_exception:
        harness.charm.resource_handler.apply()
    assert isinstance(harness.model.unit.status, BlockedStatus)


@pytest.mark.parametrize(
    "gateway_relation, charm_config, expected_data",
    (
        (
            "ingress-gateway",
            {"istio.gateway.name": "test-name", "istio.gateway.namespace": "test-model"},
            {"gateway_name": "test-name", "gateway_namespace": "test-model", "gateway_up": "true"},
        ),
        (
            "local-gateway",
            {"namespace": "test-serving"},
            {
                "gateway_name": "knative-local-gateway",
                "gateway_namespace": "test-serving",
                "gateway_up": "true",
            },
        ),
    ),
)
def test_gateway_relation_data(
    gateway_relation, charm_config, expected_data, harness, mocked_lightkube_client
):
    """Assert that the data sent through the relation is accurate."""
    harness.set_model_name("test-model")
    harness.begin()

    # Update config values with test values
    harness.update_config(charm_config)

    # Add one relation, send data, and assert the data is correct
    relation_id = harness.add_relation(gateway_relation, "app")
    # Add relation unit and "update" the relation data to trigger relation-changed hook
    harness.add_relation_unit(relation_id, "app/0")
    harness.update_relation_data(relation_id, "app", {"ingress-address": "test-address"})

    if gateway_relation == "local-gateway":
        relations = harness.charm._local_gateway_provider.model.relations[gateway_relation]
    else:
        relations = harness.charm._ingress_gateway_provider.model.relations[gateway_relation]

    for relation in relations:
        actual_data = relation.data[harness.charm.app]
        assert expected_data == actual_data

    # Add a second relation and assert the data
    relation_id = harness.add_relation(gateway_relation, "app2")
    # Add relation unit and "update" the relation data to trigger relation-changed hook
    harness.add_relation_unit(relation_id, "app2/0")
    harness.update_relation_data(relation_id, "app2", {"ingress-address": "test-address"})

    for relation in relations:
        actual_data = relation.data[harness.charm.app]
        assert expected_data == actual_data


def test_otel_collector_relation_changed(harness):
    harness.begin()
    harness.charm._apply_and_set_status = MagicMock()

    rel_id = harness.add_relation("otel-collector", "app")
    harness.update_relation_data(rel_id, "app", {"some-key": "some-value"})

    harness.charm._apply_and_set_status.assert_called_once()


def test_context_changes(harness):
    harness.update_config(
        {
            "namespace": "knative-serving",
            "istio.gateway.name": "knative-gateway",
            "istio.gateway.namespace": "istio-namespace",
        }
    )
    harness.begin()
    context = {
        "app_name": harness.charm.app.name,
        "domain": harness.model.config["domain.name"],
        "gateway_name": harness.model.config["istio.gateway.name"],
        "gateway_namespace": harness.model.config["istio.gateway.namespace"],
        "serving_namespace": harness.model.config["namespace"],
        "serving_version": harness.model.config["version"],
    }

    assert harness.charm._context == context

    harness.charm.resource_handler.apply = MagicMock()
    with does_not_raise():
        rel_id = harness.add_relation("otel-collector", "app")
        assert harness.charm._context == context

    additional_context = {"some-key": "some-value"}
    context.update(additional_context)
    with does_not_raise():
        harness.update_relation_data(rel_id, "app", additional_context)
        assert harness.charm._context == context


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
