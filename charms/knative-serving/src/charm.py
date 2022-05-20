#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from ops.model import BlockedStatus

from charm_helpers.exceptions import ErrorWithStatus
from charm_template import KubernetesManifestCharmBase
from ops.main import main

# Import defines the Generic Resource for lightkube, which is used indirectly
# when loading from yaml
from lightkube_custom_resources.operator import KnativeServing_v1alpha1


class KnativeServingCharm(KubernetesManifestCharmBase):
    """A charm for creating Knative Serving instances via the Knative Operator"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.template_files = [
            "KnativeServing.yaml.j2",
        ]

        self.serving_version = "1.1.2"

    @property
    def context_for_render(self):
        """Returns the context for rendering the template files, including config/relation data
        """
        # Use defaults for charm_name, model_name, etc.
        context = super().context_for_render
        try:
            additional_context = {
                "domain": self.model.config["domain.name"],
                "namespace": self._get_serving_namespace(),
                "version": self.serving_version,
                "gateway_name": self.model.config["istio.gateway.name"],  # TODO
                "gateway_namespace": self._get_istio_gateway_namespace(),  # TODO
            }
            context.update(additional_context)

        except Exception as e:
            msg = "Error when extracting charm context from config and relation data"
            raise CharmContextError(msg, BlockedStatus) from e

        return context

    def _get_serving_namespace(self):
        """Returns the namespace for the Knative Serving instance, defaulting to this charm's model
        """
        namespace = self.model.config["namespace"]
        # For blank or omitted namespaces, use this model's name
        if not namespace:
            namespace = self.model_name
        return namespace

    def _get_istio_gateway_namespace(self):
        """Returns the namespace for the Istio Gateway used by Knative Serving

        If config is empty, this defaults to the current model's namespace
        """
        namespace = self.model.config["istio.gateway.namespace"]
        # For blank or omitted namespaces, use this model's name
        if not namespace:
            namespace = self.model_name
        return namespace


class CharmContextError(ErrorWithStatus):
    """Raised when an error occurs when extracting the charm context from config and relation data
    """
    pass


if __name__ == "__main__":
    main(KnativeServingCharm)
