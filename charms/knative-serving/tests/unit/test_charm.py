from unittest.mock import MagicMock, call

import pytest

from charm import KnativeServingCharm
from ops.testing import Harness


@pytest.fixture
def harness():
    """Returns a harnessed charm with leader == True"""
    harness = Harness(KnativeServingCharm)
    harness.set_leader(True)
    return harness


@pytest.fixture()
def lightkube_codecs(mocker):
    """Yields a mocked lightkube codecs"""
    yield mocker.patch("charm_template.codecs")


@pytest.fixture()
def lightkube_client(mocker):
    """Mocks Lightkube.Client() to return a MagicMock object instead of a Client

    Yields this child MagicMock object for convenient access
    """
    mocked_lightkube_client = MagicMock()
    mocked_lightkube_client_factory = mocker.patch("charm_template.Client")
    mocked_lightkube_client_factory.return_value = mocked_lightkube_client
    yield mocked_lightkube_client


def test_install(harness, lightkube_client, mocker):
    # Arrange
    harness.begin()
    sample_resources = ["some yaml"]
    mocked_render_manifests = mocker.patch("charm.KnativeServingCharm.render_manifests", return_value=sample_resources)

    # Act
    harness.charm.on.install.emit()

    # Assert
    mocked_render_manifests.assert_called_once()
    lightkube_client.apply_many.assert_called_once_with(sample_resources)


