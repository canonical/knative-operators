# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from unittest.mock import MagicMock

import pytest
from charmed_kubeflow_chisme.lightkube.mocking import FakeApiError
from ops.model import ActiveStatus, BlockedStatus


def test_events(harness, mocked_lightkube_client):
    # Test install and config_changed event handlers are called
    harness.begin()
    harness.charm._on_install = MagicMock()
    harness.charm._on_config_changed = MagicMock()

    harness.charm.on.install.emit()
    harness.charm._on_install.assert_called_once()

    harness.charm.on.config_changed.emit()
    harness.charm._on_config_changed.assert_called_once()


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
