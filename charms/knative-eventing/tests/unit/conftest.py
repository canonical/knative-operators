# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest import mock

import pytest
from ops.testing import Harness

from charm import KnativeEventingCharm


@pytest.fixture()
def mocked_lightkube_client_class(mocker):
    """Prevents lightkube clients from being created, returning a mock instead."""
    mocked_lightkube_client_class = mocker.patch(
        "charmed_kubeflow_chisme.kubernetes._kubernetes_resource_handler.Client"
    )
    mocked_lightkube_client_class.return_value = mock.MagicMock()
    yield mocked_lightkube_client_class


@pytest.fixture()
def mocked_lightkube_client(mocked_lightkube_client_class):
    """Prevents lightkube clients from being created, returning a mock instead."""
    yield mocked_lightkube_client_class()


@pytest.fixture
def harness():
    """Returns a harnessed charm with leader == True."""
    harness = Harness(KnativeEventingCharm)
    harness.set_leader(True)
    return harness
