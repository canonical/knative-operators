#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import traceback

from ops.main import main
from ops.pebble import Layer
from ops.charm import CharmBase
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus
from jinja2 import Environment, FileSystemLoader
from lightkube import ApiError, Client, codecs

logger = logging.getLogger(__name__)


class KnativeOperatorCharm(CharmBase):
    """A Juju Charm for Training Operator"""

    def __init__(self, *args):
        super().__init__(*args)

        self.logger = logging.getLogger(__name__)
        self.interfaces = ""

        self._name = self.model.app.name
        self._namespace = self.model.name
        self._operator_service = "/ko-app/operator"
        self.env = Environment(loader=FileSystemLoader('src'))
        self._container = self.unit.get_container(self._name)
        self._resources_files = {
             "auth_manifests.yaml",
             "service_account.yaml",
             "crds_manifests.yaml",
             # Skipping config manifests for now
             # "config_manifests.yaml",
        }
        self._context = {"namespace": self._namespace, "name": self._name}

        self.lightkube_client = Client(namespace=self._namespace, field_manager="lightkube")
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.config_changed, self._on_install)
        self.framework.observe(
            self.on.knative_operator_pebble_ready,
            self._on_knative_operator_pebble_ready,
        )

    @property
    def _knative_operator_layer(self) -> Layer:
        """Returns a pre-configured Pebble layer."""

        layer_config = {
            "summary": "knative-operator layer",
            "description": "pebble config layer for knative-operator",
            "services": {
                self._operator_service: {
                    "override": "replace",
                    "summary": "entrypoint of the knative-operator image",
                    "command": self._operator_service,
                    "startup": "enabled",
                    "environment": {
                        "POD_NAME": self._name,
                        "SYSTEM_NAMESPACE": self._namespace,
                        "METRICS_DOMAIN": "knative.dev/operator",
                        "CONFIG_LOGGING_NAME": "config-loggig",
                        "CONFIG_OBSERVABILITY_NAME": "config-observability",
                    },
                }
            },
        }
        return Layer(layer_config)

    def _update_layer(self) -> None:
        """Updates the Pebble configuration layer if changed."""
        if not self._container.can_connect():
            self.unit.status = MaintenanceStatus("Waiting for pod startup to complete")
            return

        # Get current config
        current_layer = self._container.get_plan()
        # Create a new config layer
        new_layer = self._knative_operator_layer
        if current_layer.services != new_layer.services:
            self._container.add_layer(self._operator_service, new_layer, combine=True)
            logging.info("Pebble plan updated with new configuration")
        self._container.restart(self._operator_service)

    def _apply_all_resources(self) -> None:
        """Helper method to create Kubernetes resources."""
        for filename in self._resources_files:
            manifest = self.env.get_template(filename).render(self._context)
            for obj in codecs.load_all_yaml(manifest):
                self.lightkube_client.apply(obj)

    def _on_install(self, event):
        """Event handler for InstallEvent."""

        # Update Pebble configuration layer if it has changed
        self._update_layer()

        # Patch/create Kubernetes resources
        try:
            self.unit.status = MaintenanceStatus("Applying resources")
            self._apply_all_resources()
        except ApiError as e:
            logging.error(traceback.format_exc())
            self.unit.status = BlockedStatus(
                f"Applying resources failed with code {str(e.status.code)}."
            )
            if e.status.code == 403:
                logging.error(
                    "Received Forbidden (403) error when creating auth resources."
                    "This may be due to the charm lacking permissions to create"
                    "cluster-scoped resources."
                    "Charm must be deployed with --trust"
                )
                event.defer()
                return
        else:
            self.unit.status = ActiveStatus()

    def _on_knative_operator_pebble_ready(self, _):
        """Event handler for on PebbleReadyEvent"""
        self._update_layer()


if __name__ == "__main__":
    main(KnativeOperatorCharm)
