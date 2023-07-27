# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Knative Eventing custom resource classes."""

from lightkube.generic_resource import create_namespaced_resource

# Knative Operator's KnativeEventing CRDs
KnativeEventing_v1beta1 = create_namespaced_resource(
    group="operator.knative.dev",
    version="v1beta1",
    kind="KnativeEventing",
    plural="knativeeventings",
    verbs=None,
)
