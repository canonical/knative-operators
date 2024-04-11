# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
"""Constants module including constants used in tests."""
from pathlib import Path

import yaml

KNATIVE_EVENTING_NAMESPACE = "knative-eventing"
KNATIVE_SERVING_NAMESPACE = "knative-serving"
KNATIVE_SERVING_SERVICE = "services.serving.knative.dev"
KNATIVE_OPERATOR_METADATA = yaml.safe_load(
    Path("./charms/knative-operator/metadata.yaml").read_text()
)
KNATIVE_OPERATOR_IMAGE = KNATIVE_OPERATOR_METADATA["resources"]["knative-operator-image"][
    "upstream-source"
]
KNATIVE_OPERATOR_WEBHOOK_IMAGE = KNATIVE_OPERATOR_METADATA["resources"][
    "knative-operator-webhook-image"
]["upstream-source"]
KNATIVE_OPERATOR_RESOURCES = {
    "knative-operator-image": KNATIVE_OPERATOR_IMAGE,
    "knative-operator-webhook-image": KNATIVE_OPERATOR_WEBHOOK_IMAGE,
}

ISTIO_CHANNEL = "1.17/stable"
ISTIO_PILOT = "istio-pilot"
ISTIO_PILOT_TRUST = True
ISTIO_GATEWAY = "istio-gateway"
ISTIO_GATEWAY_APP_NAME = "istio-ingressgateway"
ISTIO_GATEWAY_TRUST = True
