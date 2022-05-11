import pytest
from charm import Operator
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness


@pytest.fixture
def harness():
    return Harness(Operator)


@pytest.fixture(autouse=True)
def lkclient(mocker):
    yield mocker.patch("charm.Client")


EXPECTED = {
    ("Deployment", "net-istio-controller"),
    # TODO: Temporarily not applied
    # ("Gateway", "knative-ingress-gateway"),
    ("PeerAuthentication", "webhook"),
    ("PeerAuthentication", "domainmapping-webhook"),
    ("PeerAuthentication", "net-istio-webhook"),
    ("ClusterRole", "knative-serving-istio"),
    ("ConfigMap", "config-istio"),
}


def test_not_leader(harness):
    harness.begin_with_initial_hooks()
    assert isinstance(harness.charm.model.unit.status, WaitingStatus)


def test_missing_gateway_relation(harness):
    harness.set_leader(True)
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == BlockedStatus(
        "Missing gateway relation with istio-pilot"
    )


def test_too_many_gateway_relations(harness):
    harness.set_leader(True)
    rel_id_one = harness.add_relation("gateway", "app_one")
    harness.add_relation_unit(rel_id_one, "app_one/0")
    harness.update_relation_data(
        rel_id_one,
        "app_one",
        {},
    )
    rel_id_two = harness.add_relation("gateway", "app_two")
    harness.add_relation_unit(rel_id_two, "app_two/0")
    harness.update_relation_data(
        rel_id_two,
        "app_two",
        {},
    )
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == BlockedStatus("Too many istio-gateway-name relations")


def test_missing_gateway_name(harness):
    gateway_namespace = "important-gateway-namespace"
    istio_pilot = "istio-pilot"

    harness.set_leader(True)
    harness.begin_with_initial_hooks()
    rel_id = harness.add_relation("gateway", istio_pilot)
    harness.add_relation_unit(rel_id, f"{istio_pilot}/0")
    harness.update_relation_data(
        rel_id,
        istio_pilot,
        {"gateway_namespace": gateway_namespace},
    )
    assert harness.charm.model.unit.status == BlockedStatus(
        "Missing gateway name in gateway relation data. Waiting for gateway creation in istio-pilot"
    )


def test_missing_gateway_namespace(harness):
    gateway_name = "important-gateway-name"
    istio_pilot = "istio-pilot"

    harness.set_leader(True)
    rel_id = harness.add_relation("gateway", istio_pilot)
    harness.add_relation_unit(rel_id, f"{istio_pilot}/0")
    harness.update_relation_data(
        rel_id,
        istio_pilot,
        {"gateway_name": gateway_name},
    )
    harness.begin_with_initial_hooks()

    assert harness.charm.model.unit.status == BlockedStatus(
        "Missing gateway namespace in gateway relation data"
    )


def test_gateway_relation_after_install(harness):
    gateway_name = "important-gateway-name"
    gateway_namespace = "important-gateway-namespace"
    istio_pilot = "istio-pilot"

    harness.set_leader(True)
    harness.begin_with_initial_hooks()
    rel_id = harness.add_relation("gateway", istio_pilot)
    harness.add_relation_unit(rel_id, f"{istio_pilot}/0")
    harness.update_relation_data(
        rel_id,
        istio_pilot,
        {"gateway_name": gateway_name, "gateway_namespace": gateway_namespace},
    )
    istio_app = harness.model.get_app(istio_pilot)
    gateway_data = harness.model.relations["gateway"][0].data[istio_app]
    assert gateway_data["gateway_name"] == gateway_name
    assert gateway_data["gateway_namespace"] == gateway_namespace


def test_updating_gateway_relation(harness):
    istio_pilot = "istio-pilot"

    harness.set_leader(True)
    rel_id = harness.add_relation("gateway", istio_pilot)
    harness.add_relation_unit(rel_id, f"{istio_pilot}/0")
    harness.update_relation_data(
        rel_id,
        istio_pilot,
        {
            "gateway_name": "important-gateway-name",
            "gateway_namespace": "important-gateway-namespace",
        },
    )
    harness.begin_with_initial_hooks()

    # update relation data
    expected_gateway_name = "updated-gateway-name"
    expected_gateway_namespace = "updated-gateway-namespace"
    harness.update_relation_data(
        rel_id,
        istio_pilot,
        {"gateway_name": expected_gateway_name, "gateway_namespace": expected_gateway_namespace},
    )
    istio_app = harness.model.get_app(istio_pilot)
    gateway_data = harness.model.relations["gateway"][0].data[istio_app]
    assert gateway_data["gateway_name"] == expected_gateway_name
    assert gateway_data["gateway_namespace"] == expected_gateway_namespace


def test_setup(harness, lkclient):
    gateway_name = "important-gateway-name"
    gateway_namespace = "important-gateway-namespace"

    harness.set_leader(True)
    rel_id = harness.add_relation("gateway", "istio-pilot")
    harness.add_relation_unit(rel_id, "istio-pilot/0")
    harness.update_relation_data(
        rel_id,
        "istio-pilot",
        {"gateway_name": gateway_name, "gateway_namespace": gateway_namespace},
    )
    harness.begin_with_initial_hooks()

    harness.charm.on.install.emit()

    applied = {(c.args[0].kind, c.args[0].metadata.name) for c in lkclient.mock_calls if c.args}

    assert EXPECTED == applied

    assert harness.charm.model.unit.status == ActiveStatus()

    # assert correct gateway relation data
    istio_app = harness.model.get_app("istio-pilot")
    gateway_data = harness.model.relations["gateway"][0].data[istio_app]
    assert gateway_data["gateway_name"] == gateway_name
    assert gateway_data["gateway_namespace"] == gateway_namespace


def test_remove(harness, lkclient):
    harness.set_leader(True)
    rel_id = harness.add_relation("gateway", "istio-pilot")
    harness.add_relation_unit(rel_id, "istio-pilot/0")
    harness.update_relation_data(
        rel_id,
        "istio-pilot",
        {
            "gateway_name": "important-gateway-name",
            "gateway_namespace": "important-gateway-namespace",
        },
    )
    harness.begin()

    harness.charm.on.remove.emit()

    applied = {(c.args[0].__name__, c.args[1]) for c in lkclient.mock_calls if c.args}

    assert EXPECTED == applied
