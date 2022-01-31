from unittest.mock import call

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
    ("ClusterRole", "knative-serving-addressable-resolver"),
    ("ClusterRole", "knative-serving-admin"),
    ("ClusterRole", "knative-serving-aggregated-addressable-resolver"),
    ("ClusterRole", "knative-serving-core"),
    ("ClusterRole", "knative-serving-namespaced-admin"),
    ("ClusterRole", "knative-serving-namespaced-edit"),
    ("ClusterRole", "knative-serving-namespaced-view"),
    ("ClusterRole", "knative-serving-podspecable-binding"),
    ("ClusterRoleBinding", "knative-serving-controller-addressable-resolver"),
    ("ClusterRoleBinding", "knative-serving-controller-admin"),
    ("ConfigMap", "config-autoscaler"),
    ("ConfigMap", "config-defaults"),
    ("ConfigMap", "config-deployment"),
    ("ConfigMap", "config-domain"),
    ("ConfigMap", "config-features"),
    ("ConfigMap", "config-gc"),
    ("ConfigMap", "config-leader-election"),
    ("ConfigMap", "config-logging"),
    ("ConfigMap", "config-network"),
    ("ConfigMap", "config-observability"),
    ("ConfigMap", "config-tracing"),
    ("CustomResourceDefinition", "certificates.networking.internal.knative.dev"),
    ("CustomResourceDefinition", "clusterdomainclaims.networking.internal.knative.dev"),
    ("CustomResourceDefinition", "configurations.serving.knative.dev"),
    ("CustomResourceDefinition", "domainmappings.serving.knative.dev"),
    ("CustomResourceDefinition", "images.caching.internal.knative.dev"),
    ("CustomResourceDefinition", "ingresses.networking.internal.knative.dev"),
    ("CustomResourceDefinition", "metrics.autoscaling.internal.knative.dev"),
    ("CustomResourceDefinition", "podautoscalers.autoscaling.internal.knative.dev"),
    ("CustomResourceDefinition", "revisions.serving.knative.dev"),
    ("CustomResourceDefinition", "routes.serving.knative.dev"),
    ("CustomResourceDefinition", "serverlessservices.networking.internal.knative.dev"),
    ("CustomResourceDefinition", "services.serving.knative.dev"),
    ("Deployment", "controller"),
    ("Service", "controller"),
    ("ServiceAccount", "controller"),
}


def test_setup(harness, lkclient):
    harness.set_leader(True)
    harness.begin()

    harness.charm.on.install.emit()

    assert lkclient.mock_calls[0] == call(field_manager="None-knative-controller")

    applied = {(c.args[0].kind, c.args[0].metadata.name) for c in lkclient.mock_calls if c.args}

    assert EXPECTED == applied

    assert harness.charm.model.unit.status == ActiveStatus()


def test_remove(harness, lkclient):
    harness.set_leader(True)
    harness.begin()

    harness.charm.on.remove.emit()

    assert lkclient.mock_calls[0] == call(field_manager="None-knative-controller")
    applied = {(c.args[0].__name__, c.args[1]) for c in lkclient.mock_calls if c.args}

    assert EXPECTED == applied
