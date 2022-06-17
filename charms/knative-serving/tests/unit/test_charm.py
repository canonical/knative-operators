# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from k8s_resource_handler.exceptions import ReconcileError
from k8s_resource_handler.lightkube.mocking import FakeApiError
from ops.model import ActiveStatus, BlockedStatus


def test_events(harness, mocked_lightkube_client, mocker):
    # Test install and config_changed event handlers are called
    harness.begin()
    install = mocker.patch("charm.KnativeServingCharm._on_install")
    config_changed = mocker.patch("charm.KnativeServingCharm._on_config_changed")
    remove = mocker.patch("charm.KnativeServingCharm._on_remove")

    harness.charm.on.install.emit()
    install.assert_called_once()
    install.reset_mock()

    harness.charm.on.config_changed.emit()
    config_changed.assert_called_once()
    config_changed.reset_mock()

    harness.charm.on.remove.emit()
    remove.assert_called_once()
    remove.reset_mock()


def test_on_install_active(harness, mocked_lightkube_client, mocker):
    mocked_apply = mocker.patch(
        "k8s_resource_handler.kubernetes._kubernetes_resource_handler.KubernetesResourceHandler.apply"
    )
    mocked_apply.return_value = None

    harness.begin()
    harness.charm.on.install.emit()
    mocked_apply.assert_called()
    assert harness.model.unit.status == ActiveStatus()


@pytest.mark.parametrize(
    "apply_error, raised_exception, expected_blocked_message",
    (
        (FakeApiError(400), pytest.raises(FakeApiError), "ApiError: 400"),
        (
            FakeApiError(403),
            pytest.raises(ReconcileError),
            "ReconcileError: Failed to reconcile charm resources",
        ),
    ),
)
def test_on_install_blocked(
    apply_error,
    raised_exception,
    expected_blocked_message,
    harness,
    mocked_lightkube_client,
    mocker,
):
    mocked_apply = mocker.patch(
        "k8s_resource_handler.kubernetes._kubernetes_resource_handler.KubernetesResourceHandler.apply"
    )
    mocked_apply.side_effect = apply_error

    harness.begin()
    with raised_exception:
        harness.charm.on.install.emit()
    assert harness.model.unit.status == BlockedStatus(expected_blocked_message)
