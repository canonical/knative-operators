#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""A Juju charm for Knative Serving."""

import glob
import logging
import traceback
from pathlib import Path

from k8s_resource_handler.exceptions import ReconcileError
from k8s_resource_handler.kubernetes import (  # noqa N813
    KubernetesResourceHandler as krh,
)
from lightkube.core.exceptions import ApiError
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus

from lightkube_custom_resources.operator import KnativeServing_v1alpha1  # noqa F401

logger = logging.getLogger(__name__)


class KnativeServingCharm(CharmBase):
    """A charm for creating Knative Serving instances via the Knative Operator."""

    def __init__(self, *args):
        super().__init__(*args)

        self._app_name = self.app.name
        self._namespace = self.model.name
        # FIXME: if following the factory design pattern
        # use appropriate factory methods
        self._t = lambda: self._template_files
        self._c = lambda: self._context

        self.resource_handler = krh(
            template_files_factory=self._t,
            context_factory=self._c,
            field_manager=self._namespace,
        )
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.remove, self._on_remove)

    def _on_install(self, _):
        try:
            self.resource_handler.apply()
        # TODO: change ReconcileError to new name
        except (ApiError, ReconcileError) as e:
            if isinstance(e, ApiError):
                logger.debug(traceback.format_exc())
                logger.info(
                    f"Applying resources failed with ApiError status code {str(e.status.code)}"
                )
                self.unit.status = BlockedStatus(f"ApiError: {str(e.status.code)}")
            elif isinstance(e, ReconcileError):
                logger.info(f"Applying resources failed with message {str(e.msg)}")
                self.unit.status = BlockedStatus(f"ReconcileError: {str(e.msg)}")
        else:
            # TODO: once the resource handler v0.0.2 is out,
            # let's use the compute_status() method to set (or not)
            # an active status
            self.unit.status = ActiveStatus()

    def _on_config_changed(self, event):
        self._on_install(event)

    def _on_remove(self, _):
        raise NotImplementedError

    @property
    def _template_files(self):
        # FIXME: is this something that will change? Probably not.
        src_dir = Path("src")
        manifests_dir = src_dir / "manifests"
        serving_manifests = [file for file in glob.glob(f"{manifests_dir}/*.yaml.j2")]
        return serving_manifests

    @property
    def _context(self):
        # TODO: if we stick to the factory design, implement
        # it correctly. This is temporal.
        context = {
            "app_name": self._app_name,
            "domain": self.model.config["domain.name"],
            "gateway_name": self.model.config["istio.gateway.name"],
            "gateway_namespace": self.model.config["istio.gateway.namespace"],
            "serving_namespace": self.model.config["serving.namespace"],
            "serving_version": self.model.config["serving.version"],
        }
        return context


if __name__ == "__main__":
    main(KnativeServingCharm)
