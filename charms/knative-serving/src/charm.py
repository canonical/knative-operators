#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""A Juju charm for Knative Serving."""

import glob
import logging
import traceback
from pathlib import Path

import yaml
from charmed_kubeflow_chisme.exceptions import ErrorWithStatus, GenericCharmRuntimeError
from charmed_kubeflow_chisme.kubernetes import KubernetesResourceHandler as KRH  # noqa N813
from charmed_kubeflow_chisme.lightkube.batch import delete_many
from charms.istio_pilot.v0.istio_gateway_info import GatewayProvider
from lightkube import Client
from lightkube.core.exceptions import ApiError
from lightkube.resources.apiextensions_v1 import CustomResourceDefinition
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus

from image_management import parse_image_config, remove_empty_images, update_images
from lightkube_custom_resources.operator import KnativeServing_v1beta1  # noqa F401

logger = logging.getLogger(__name__)


CUSTOM_IMAGE_CONFIG_NAME = "custom_images"
DEFAULT_IMAGES = {"net-istio-webhook/webhook": "charmedkubeflow/net-istio-webhook:1.16.0-4214206"}


class KnativeServingCharm(CharmBase):
    """A charm for creating Knative Serving instances via the Knative Operator."""

    def __init__(self, *args):
        super().__init__(*args)

        self._app_name = self.app.name
        self._namespace = self.model.name
        self._resource_handler = None
        # Instantiate the GatewayProvider class, one instance for sharing the local gateway
        # another one for sharing the ingress gateway
        self._ingress_gateway_provider = GatewayProvider(self, relation_name="ingress-gateway")
        self._local_gateway_provider = GatewayProvider(self, relation_name="local-gateway")

        self.framework.observe(self.on.config_changed, self._main)
        self.framework.observe(
            self.on["ingress-gateway"].relation_changed, self._on_ingress_gateway_relation_changed
        )
        self.framework.observe(
            self.on["local-gateway"].relation_changed, self._on_local_gateway_relation_changed
        )
        self.framework.observe(
            self.on["otel-collector"].relation_changed, self._on_otel_collector_relation_changed
        )
        self.framework.observe(self.on.remove, self._on_remove)

    def _apply_and_set_status(self):
        try:
            self.unit.status = MaintenanceStatus("Configuring/deploying resources")
            self.resource_handler.apply()
        except ApiError as e:
            logger.debug(traceback.format_exc())
            logger.error(f"Applying resources failed with ApiError status code {e.status.code}")
            self.unit.status = BlockedStatus(f"ApiError: {e.status.code}")
        except ErrorWithStatus as e:
            logger.error(e.msg)
            self.unit.status = e.status
        else:
            # TODO: once the resource handler v0.0.2 is out,
            # let's use the compute_status() method to set (or not)
            # an active status
            self.unit.status = ActiveStatus()

    def _get_custom_images(self):
        """Parses custom_images from config and defaults, returning a dict of images."""
        try:
            default_images = remove_empty_images(DEFAULT_IMAGES)
            custom_images = parse_image_config(self.model.config[CUSTOM_IMAGE_CONFIG_NAME])
            custom_images = update_images(
                default_images=default_images, custom_images=custom_images
            )
        except yaml.YAMLError as err:
            logger.error(
                f"Charm Blocked due to error parsing the `custom_images` config.  "
                f"Caught error: {str(err)}"
            )
            raise ErrorWithStatus(
                "Error parsing the `custom_images` config - fix `custom_images` to unblock.  "
                "See logs for more details",
                BlockedStatus,
            )
        return custom_images

    def _main(self, event):
        if not self.model.config["namespace"]:
            self.model.unit.status = BlockedStatus("Config item `namespace` must be set")
            return

        self._send_ingress_gateway_data()
        self._send_local_gateway_data()

        # Check the KnativeServing CRD is present; otherwise defer
        lightkube_client = Client()
        try:
            lightkube_client.get(CustomResourceDefinition, "knativeservings.operator.knative.dev")
            self._apply_and_set_status()
        except ApiError as e:
            if e.status.code == 404:
                self.model.unit.status = WaitingStatus(
                    "Waiting for knative-operator CRDs to be present."
                )
                event.defer()
            else:
                raise GenericCharmRuntimeError(
                    f"Lightkube get CRD failed with error code: {e.status.code}"
                ) from e

    def _on_ingress_gateway_relation_changed(self, _) -> None:
        self._send_ingress_gateway_data()

    def _on_local_gateway_relation_changed(self, _) -> None:
        self._send_local_gateway_data()

    def _send_ingress_gateway_data(self) -> None:
        """Sends the ingress gateway info through the gateway-info relation."""
        self._ingress_gateway_provider.send_gateway_relation_data(
            gateway_name=self.model.config["istio.gateway.name"],
            gateway_namespace=self.model.config["istio.gateway.namespace"],
        )

    def _send_local_gateway_data(self) -> None:
        """Sends the local gateway info through the gateway-info relation."""
        # FIXME: The local gateway name is hardcoded in the KnativeServing.yaml.j2
        self._local_gateway_provider.send_gateway_relation_data(
            gateway_name="knative-local-gateway",
            gateway_namespace=self.model.config["namespace"],
        )

    def _on_otel_collector_relation_changed(self, _):
        """Event handler for on['otel-collector'].relation_changed."""
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
    def _otel_collector_relation_data(self):
        """Returns relation data from the otel-collector relation."""
        relation = self.model.get_relation("otel-collector")
        if relation:
            return relation.data[relation.app]
        logger.info(
            "No otel-collector relation detected, observability won't be enabled for knative-serving"  # noqa: E501
        )
        return {}

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
            "domain": self.model.config["domain.name"],
            "gateway_name": self.model.config["istio.gateway.name"],
            "gateway_namespace": self.model.config["istio.gateway.namespace"],
            "serving_namespace": self.model.config["namespace"],
            "serving_version": self.model.config["version"],
            "custom_images": self._get_custom_images(),
            "progress_deadline": self.model.config["progress-deadline"],
            "registries_skip_tag_resolving": self.model.config[
                "registries-skipping-tag-resolving"
            ],
            "http_proxy": self.model.config["http-proxy"],
            "https_proxy": self.model.config["https-proxy"],
            "no_proxy": self.model.config["no-proxy"],
        }
        if self._otel_collector_relation_data:
            context.update(self._otel_collector_relation_data)
        if self.model.config["queue_sidecar_image"]:
            context.update({"queue_sidecar_image": self.model.config["queue_sidecar_image"]})

        return context

    @property
    def resource_handler(self):
        """Returns an instance of KubernetesResourceHandler."""
        if not self._resource_handler:
            self._resource_handler = KRH(
                template_files=self._template_files,
                context=self._context,
                field_manager=self._namespace,
            )
        return self._resource_handler


if __name__ == "__main__":
    main(KnativeServingCharm)
