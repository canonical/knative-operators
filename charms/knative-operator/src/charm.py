#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import traceback

from ops.main import main
from ops.pebble import ChangeError, Layer
from ops.charm import CharmBase
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus
from jinja2 import Environment, FileSystemLoader
from lightkube import ApiError, Client, codecs

logger = logging.getLogger(__name__)


class KnativeOperatorCharm(CharmBase):
    """A Juju Charm for Training Operator"""

    def __init__(self, *args):
        super().__init__(*args)

        self._app_name = self.model.app.name
        self._namespace = self.model.name
        self._operator_service = "/ko-app/operator"
        self._container = self.unit.get_container(self._app_name)
        self.env = Environment(loader=FileSystemLoader("src"))
        self._resources_files = (
            "auth_manifests.yaml",
            "service_account.yaml",
            "crds_manifests.yaml",
            "istio_ns.yaml",
            # Skipping config manifests for now
            # "config_manifests.yaml",
        )
        self._context = {"namespace": self._namespace, "name": self._app_name}

        self.lightkube_client = Client(namespace=self._namespace, field_manager="lightkube")
        for event in [self.on.install, self.on.config_changed]:
            self.framework.observe(event, self._main)
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
                        "POD_NAME": self._app_name,
                        "SYSTEM_NAMESPACE": self._namespace,
                        "METRICS_DOMAIN": "knative.dev/operator",
                        "CONFIG_LOGGING_NAME": "config-loggig",
                        "CONFIG_OBSERVABILITY_NAME": "config-observability",
                    },
                }
            },
        }
        return Layer(layer_config)

    def _update_layer(self, event) -> None:
        """Updates the Pebble configuration layer if changed."""
        if not self._container.can_connect():
            self.unit.status = MaintenanceStatus("Waiting for pod startup to complete")
            event.defer()
            return

        # Get current config
        current_layer = self._container.get_plan()
        # Create a new config layer
        new_layer = self._knative_operator_layer
        if current_layer.services != new_layer.services:
            self._container.add_layer(self._operator_service, new_layer, combine=True)
            try:
                logger.info("Pebble plan updated with new configuration, replanning")
                self._container.replan()
            except ChangeError:
                logger.error(traceback.format_exc())
                self.unit.status = BlockedStatus("Failed to replan")
        self.unit.status = ActiveStatus()

    def _apply_all_resources(self) -> None:
        """Helper method to create Kubernetes resources."""
        try:
            for filename in self._resources_files:
                manifest = self.env.get_template(filename).render(self._context)
                for obj in codecs.load_all_yaml(manifest):
                    self.lightkube_client.apply(obj)
        except ApiError as e:
            logger.error(traceback.format_exc())
            self.unit.status = BlockedStatus(
                f"Applying resources failed with code {str(e.status.code)}."
            )
            if e.status.code == 403:
                logger.error(
                    "Received Forbidden (403) error when creating auth resources."
                    "This may be due to the charm lacking permissions to create"
                    "cluster-scoped resources."
                    "Charm must be deployed with --trust"
                )
                return
        else:
            self.unit.status = ActiveStatus()

    def _main(self, event):
        """Event handler for changing Pebble configuration and applying k8s resources."""
        # Update Pebble configuration layer if it has changed
        self.unit.status = MaintenanceStatus("Configuring Pebble layer")
        self._update_layer(event)

        # Apply Kubernetes resources
        self.unit.status = MaintenanceStatus("Applying resources")
        self._apply_all_resources()

    def _on_knative_operator_pebble_ready(self, event):
        """Event handler for on PebbleReadyEvent"""
        self.unit.status = MaintenanceStatus("Configuring Pebble layer")
        self._update_layer(event)


if __name__ == "__main__":
    main(KnativeOperatorCharm)
