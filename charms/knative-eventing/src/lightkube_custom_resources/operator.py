# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Knative Eventing custom resource classes."""

from lightkube.generic_resource import create_namespaced_resource

# Knative Operator's KnativeEventing CRDs
# version 1.1.x
KnativeEventing_v1alpha1 = create_namespaced_resource(
    group="operator.knative.dev",
    version="v1alpha1",
    kind="KnativeEventing",
    plural="knativeeventings",
    verbs=None,
)
