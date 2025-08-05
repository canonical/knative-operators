# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import json
from contextlib import nullcontext as does_not_raise
from unittest.mock import MagicMock, patch

import pytest
import yaml
from charmed_kubeflow_chisme.exceptions import ErrorWithStatus, GenericCharmRuntimeError
from charmed_kubeflow_chisme.lightkube.mocking import FakeApiError
from lightkube import ApiError
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus

from charm import CUSTOM_IMAGE_CONFIG_NAME, DEFAULT_IMAGES_FILE

with open(DEFAULT_IMAGES_FILE, "r") as json_file:
    DEFAULT_IMAGES = json.load(json_file)


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
    # Test install event handlers are called
    harness.begin()
    harness.charm._main = MagicMock()
    harness.charm._on_otel_collector_relation_changed = MagicMock()

    harness.charm.on.config_changed.emit()
    harness.charm._main.assert_called_once()

    rel_id = harness.add_relation("otel-collector", "app")
    harness.update_relation_data(rel_id, "app", {"some-key": "some-value"})
    harness.charm._on_otel_collector_relation_changed.assert_called_once()


@patch("charm.Client")
def test_active(lk_client, harness, mocked_lightkube_client):
    harness.begin_with_initial_hooks()
    rel_id = harness.add_relation("otel-collector", "app")
    harness.update_relation_data(rel_id, "app", {"some-key": "some-value"})
    harness.charm.resource_handler.apply = MagicMock()
    harness.charm.resource_handler.apply.return_value = None
    assert harness.model.unit.status == ActiveStatus()


@patch("charm.Client")
def test_missing_knative_eventing_crd(lk_client, harness, mocker, mocked_lightkube_client):
    harness.begin()

    # Set the side effect of Client to a FakeApiError
    lk_client.return_value.get.side_effect = _FakeApiError(code=404)

    # Set the relation to otel-collector
    rel_id = harness.add_relation("otel-collector", "app")
    harness.update_relation_data(rel_id, "app", {"some-key": "some-value"})

    harness.charm.on.install.emit()
    assert isinstance(harness.model.unit.status, WaitingStatus)


@patch("charm.Client")
def test_error_getting_knative_eventing_crd(lk_client, harness, mocker, mocked_lightkube_client):
    harness.begin()

    # Set the side effect of Client to a FakeApiError
    lk_client.return_value.get.side_effect = _FakeApiError(code=403)

    # Set the relation to otel-collector
    rel_id = harness.add_relation("otel-collector", "app")
    harness.update_relation_data(rel_id, "app", {"some-key": "some-value"})

    with pytest.raises(GenericCharmRuntimeError):
        harness.charm.on.install.emit()


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


def test_otel_collector_relation_changed(harness):
    harness.begin()
    harness.charm._apply_and_set_status = MagicMock()

    rel_id = harness.add_relation("otel-collector", "app")
    harness.update_relation_data(rel_id, "app", {"some-key": "some-value"})

    harness.charm._apply_and_set_status.assert_called_once()


def test_context_changes(harness):
    harness.begin()
    context = {
        "app_name": harness.charm.app.name,
        "eventing_namespace": harness.model.name,
        "eventing_version": harness.model.config["version"],
        CUSTOM_IMAGE_CONFIG_NAME: DEFAULT_IMAGES,
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


@pytest.mark.parametrize(
    "custom_image_config, expected_custom_images",
    [
        (
            yaml.dump({"name1": "image1", "name2": "image2"}),
            {**DEFAULT_IMAGES, **{"name1": "image1", "name2": "image2"}},
        ),
        (
            yaml.dump({}),
            DEFAULT_IMAGES,
        ),
    ],
)
def test_custom_images_config_context(custom_image_config, expected_custom_images, harness):
    """Asserts that the custom_images context is as expected.

    Note: This test is trivial now, where custom_image_config always equals custom_images, but
    once we've implemented rocks for this charm those will be used as the defaults and this test
    will be more helpful.
    """
    harness.update_config({"custom_images": custom_image_config})
    harness.begin()

    actual_context = harness.charm._context
    actual_custom_images = actual_context["custom_images"]

    assert actual_custom_images == expected_custom_images


def test_custom_images_config_context_with_incorrect_config(harness):
    """Asserts that the custom_images context correctly raises on corrupted config input."""
    harness.update_config({"custom_images": "{"})
    harness.begin()

    with pytest.raises(ErrorWithStatus) as err:
        harness.charm._context
        assert isinstance(err.status, BlockedStatus)


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
