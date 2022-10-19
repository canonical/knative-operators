#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""A Juju charm for Knative Eventing."""

import glob
import logging
import traceback
from pathlib import Path

from charmed_kubeflow_chisme.exceptions import ErrorWithStatus
from charmed_kubeflow_chisme.kubernetes import (  # noqa N813
    KubernetesResourceHandler as KRH,
)
from charmed_kubeflow_chisme.lightkube.batch import delete_many
from lightkube.core.exceptions import ApiError
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus

from lightkube_custom_resources.operator import KnativeEventing_v1alpha1  # noqa F401

logger = logging.getLogger(__name__)


class KnativeEventingCharm(CharmBase):
    """A charm for creating Knative Eventing instances via the Knative Operator."""

    def __init__(self, *args):
        super().__init__(*args)

        self._app_name = self.app.name
        self._namespace = self.model.name
        self._context_ext = None
        self._resource_handler = None

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on["otel-collector"].relation_changed, self._on_otel_collector_relation_changed)
        self.framework.observe(self.on.remove, self._on_remove)

    def _apply_and_set_status(self):
        try:
            self.unit.status = MaintenanceStatus("Configuring/deploying resources")
            self.resource_handler.apply()
        except (ApiError, ErrorWithStatus) as e:
            logger.debug(traceback.format_exc())
            if isinstance(e, ApiError):
                logger.info(f"Applying resources failed with ApiError status code {e.status.code}")
                self.unit.status = BlockedStatus(f"ApiError: {e.status.code}")
            else:
                logger.info(e.msg)
                self.unit.status = e.status
        else:
            # TODO: once the resource handler v0.0.2 is out,
            # let's use the compute_status() method to set (or not)
            # an active status
            self.unit.status = ActiveStatus()

    def _on_install(self, _):
        if not self.model.config["namespace"]:
            self.model.unit.status = BlockedStatus("Config item `namespace` must be set")
            return
        self._apply_and_set_status()

    def _on_config_changed(self, _):
        self._apply_and_set_status()

    def _get_relation_data(self, relation_name: str, source):
        """Returns relation data from a specified relation name and source.

        Args:
            relation_name: the name of the endpoint for this charm
            source: the application or unit whose data will be retrieved
        """
        relation = self.model.get_relation(relation_name)
        return relation.data[source]

    def _on_otel_collector_relation_changed(self, event):
        """Event handler for on['otel-collector'].relation_changed."""
        # Read relation data from knative-operator application bucket
        otel_collector_rel_data = self._get_relation_data("otel-collector", event.app)
        if otel_collector_rel_data:
            # Extend context to render manifests
            self._context_ext = otel_collector_rel_data
            # Reset resource handler
            self._resource_handler = None
            self._apply_and_set_status()

    def _on_remove(self, _):
        self.unit.status = MaintenanceStatus("Removing k8s resources")
        manifests = self.resource_handler.render_manifests()
        try:
            delete_many(self.resource_handler.lightkube_client, manifests)
        except ApiError as e:
            logger.warning(f"Failed to delete resources: {manifests} with: {e}")
            raise e
        self.unit.status = MaintenanceStatus("K8s resources removed")

        
    @property
    def _template_files(self):
        src_dir = Path("src")
        manifests_dir = src_dir / "manifests"
        eventing_manifests = [file for file in glob.glob(f"{manifests_dir}/*.yaml.j2")]
        return eventing_manifests

    @property
    def _context(self):
        context = {
            "app_name": self._app_name,
            "eventing_namespace": self.model.config["namespace"],
        }
        if self._context_ext:
            context.update(self._context_ext)
        return context

    @property
    def resource_handler(self):
        if not self._resource_handler:
            self._resource_handler = KRH(
                template_files=self._template_files,
                context=self._context,
                field_manager=self._namespace,
            )
        return self._resource_handler


if __name__ == "__main__":
    main(KnativeEventingCharm)
