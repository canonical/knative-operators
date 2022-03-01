import pytest
from charm import Operator
from ops.model import ActiveStatus
from ops.testing import Harness


@pytest.fixture
def harness():
    return Harness(Operator)


@pytest.fixture(autouse=True)
def lkclient(mocker):
    yield mocker.patch("charm.Client")


EXPECTED = {
    ("Deployment", "activator"),
    ("HorizontalPodAutoscaler", "activator"),
    ("PodDisruptionBudget", "activator-pdb"),
    ("Service", "activator-service"),
}


def test_setup(harness, lkclient):
    harness.set_leader(True)
    harness.begin()

    harness.charm.on.install.emit()

    applied = {(c.args[0].kind, c.args[0].metadata.name) for c in lkclient.mock_calls if c.args}

    assert EXPECTED == applied

    assert harness.charm.model.unit.status == ActiveStatus()


def test_remove(harness, lkclient):
    harness.set_leader(True)
    harness.begin()

    harness.charm.on.remove.emit()

    applied = {(c.args[0].__name__, c.args[1]) for c in lkclient.mock_calls if c.args}

    assert EXPECTED == applied
