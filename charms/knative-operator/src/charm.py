#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju Charm for knative-operator."""

import glob
import logging
import traceback
from pathlib import Path

from charmed_kubeflow_chisme.exceptions import ErrorWithStatus
from charmed_kubeflow_chisme.kubernetes import (  # noqa N813
    KubernetesResourceHandler as KRH,
)
from charmed_kubeflow_chisme.lightkube.batch import delete_many
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from lightkube import ApiError
from lightkube.resources.core_v1 import Service
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus
from ops.pebble import ChangeError, Layer

REQUEST_LOG_TEMPLATE = '{"httpRequest": {"requestMethod": "{{.Request.Method}}", "requestUrl": "{{js .Request.RequestURI}}", "requestSize": "{{.Request.ContentLength}}", "status": {{.Response.Code}}, "responseSize": "{{.Response.Size}}", "userAgent": "{{js .Request.UserAgent}}", "remoteIp": "{{js .Request.RemoteAddr}}", "serverIp": "{{.Revision.PodIP}}", "referer": "{{js .Request.Referer}}", "latency": "{{.Response.Latency}}s", "protocol": "{{.Request.Proto}}"}, "traceId": "{{index .Request.Header "X-B3-Traceid"}}"}'

logger = logging.getLogger(__name__)


class KnativeOperatorCharm(CharmBase):
    """A Juju Charm for knative-operator."""

    def __init__(self, *args):
        super().__init__(*args)

        self._app_name = self.model.app.name
        self._namespace = self.model.name
        self._src_dir = Path("src")
        self._template_files_ext = None
        self._resource_handler = None

        self._scraping = MetricsEndpointProvider(
            self,
            relation_name="metrics-endpoint",
            jobs=[{"static_configs": [{"targets": [f"{self._otel_exporter_ip}:8889"]}]}],
        )
        self._operator_service = "/ko-app/operator"
        self._container = self.unit.get_container(self._app_name)
        for event in [self.on.install, self.on.config_changed]:
            self.framework.observe(event, self._main)

        self.framework.observe(
            self.on["otel-collector"].relation_changed, self._on_otel_collector_relation_changed
        )
        self.framework.observe(
            self.on.knative_operator_pebble_ready,
            self._on_knative_operator_pebble_ready,
        )
        self.framework.observe(self.on.remove, self._on_remove)

    @property
    def resource_handler(self):
        if not self._resource_handler:
            self._resource_handler = KRH(
                template_files=self._template_files,
                context=self._context,
                field_manager=self._namespace,
            )
        return self._resource_handler

    @property
    def _template_files(self):
        manifests_dir = self._src_dir / "manifests"
        eventing_manifests = [file for file in glob.glob(f"{manifests_dir}/*.yaml.j2")]
        # Extend the list of template files if needed
        # self._template_files_ext should be a list
        if self._template_files_ext:
            eventing_manifests.extend(self._template_files_ext)
        return eventing_manifests

    @property
    def _otel_exporter_ip(self):
        """Returns the ClusterIP of the otel-export service."""
        try:
            exporter_service = self.resource_handler.lightkube_client.get(
                res=Service, name="otel-export", namespace=self._namespace
            )
            exporter_ip = exporter_service.spec.clusterIP
        except ApiError as e:
            if e.status.code == 404:
                logger.info(
                    "The OpenTelemetry Collector may not be deployed yet."
                    "This may be temporary or due to a missing otel-collector relation."
                )
                return ""
            logger.error(traceback.format_exc())
            raise
        else:
            return exporter_ip

    @property
    def _context(self):
        context = {
            "namespace": self._namespace,
            "name": self._app_name,
            "requestLogTemplate": REQUEST_LOG_TEMPLATE,
        }
        return context

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
            except ChangeError as e:
                logger.error(traceback.format_exc())
                self.unit.status = BlockedStatus("Failed to replan")
                raise e
        self.unit.status = ActiveStatus()

    def _apply_all_resources(self):
        try:
            self.resource_handler.apply()
        except (ApiError, ErrorWithStatus) as e:
            logger.info(traceback.format_exc())
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

    def _main(self, event):
        """Event handler for changing Pebble configuration and applying k8s resources."""
        # Update Pebble configuration layer if it has changed
        self.unit.status = MaintenanceStatus("Configuring Pebble layer")
        self._update_layer(event)

        # Apply Kubernetes resources
        self.unit.status = MaintenanceStatus("Applying resources")
        self._apply_all_resources()

    def _on_knative_operator_pebble_ready(self, event):
        """Event handler for on PebbleReadyEvent."""
        self.unit.status = MaintenanceStatus("Configuring Pebble layer")
        self._update_layer(event)

    def _on_otel_collector_relation_changed(self, event):
        """Event handler for on['otel-collector'].relation_changed."""
        # Apply all changes only if the otel collector has not been deployed
        if not self._otel_exporter_ip:
            self.unit.status = MaintenanceStatus("Applying otel collector")
            self._template_files_ext = [
                f"{self._src_dir}/manifests/observability/collector.yaml.j2"
            ]
            # Reset the resource handler so it uses the expanded template files list
            self._resource_handler = None
            self._apply_all_resources()
        # Write to its own application bucket
        relation_data = self.model.get_relation("otel-collector", event.relation.id).data[self.app]
        # Update own application bucket with otel collector information
        relation_data.update(
            {
                "otel_collector_svc_namespace": self.model.name,
                "otel_collector_svc_name": "otel-collector",
                "otel_collector_port": "55678",
            }
        )
        self.unit.status = ActiveStatus()

    def _on_remove(self, _):
        self.unit.status = MaintenanceStatus("Removing k8s resources")
        manifests = self.resource_handler.render_manifests()
        try:
            delete_many(self.resource_handler.lightkube_client, manifests)
        except ApiError as e:
            logger.warning(f"Failed to delete resources: {manifests} with: {e}")
            raise e
        self.unit.status = MaintenanceStatus("K8s resources removed")


if __name__ == "__main__":
    main(KnativeOperatorCharm)
