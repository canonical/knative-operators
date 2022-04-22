#!/usr/bin/env python3

import logging

from jinja2 import Environment, FileSystemLoader
from lightkube import ApiError, Client, codecs
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus

from lightkube.generic_resource import create_namespaced_resource


class Operator(CharmBase):
    """Charmed Operator."""

    def __init__(self, *args):
        super().__init__(*args)

        self.log = logging.getLogger(__name__)
        self.client = Client(field_manager=f"{self.model.name}-{self.model.app.name}")
        self.env = Environment(
            loader=FileSystemLoader("src/"),
            variable_start_string="[[",
            variable_end_string="]]",
        )

        for event in [
            self.on.install,
            self.on.leader_elected,
            self.on.upgrade_charm,
            self.on.config_changed,
            self.on.update_status,
            self.on["gateway"].relation_changed,
        ]:
            self.framework.observe(event, self.main)

        self.framework.observe(self.on.remove, self.remove)

    def apply(self, obj):
        try:
            self.client.apply(obj)
        except ApiError as err:
            if err.status.code == 415:
                self.log.error(
                    f"Got 415 response while applying {obj.metadata.name} of kind "
                    f"{obj.kind}, is ServerSideApply not available?"
                )
            raise

    def render(self):
        create_namespaced_resource(
            group="networking.istio.io",
            version="v1alpha3",
            kind="Gateway",
            plural="gateways",
            verbs=None,
        )

        create_namespaced_resource(
            group="security.istio.io",
            version="v1beta1",
            kind="PeerAuthentication",
            plural="peerauthentications",
            verbs=None,
        )

        # FIXME: remove hardcoded knative-serving
        args = {
            "name": "istio-controller",
            "namespace": self.model.name,
            "knative_serving": "knative-serving",
        }

        templates = [
            self.env.get_template("deployment.yaml.j2").render(**args),
            self.render_config_istio(args),
            self.env.get_template("rbac.yaml.j2").render(**args),
            # TODO: Temporarily removed as I try to get other gateways to work
            # env.get_template("gateway.yaml.j2").render(**args),
            self.env.get_template("peer_auth.yaml.j2").render(**args),
        ]

        return codecs.load_all_yaml("\n---\n".join(templates))

    def render_config_istio(self, args):
        istio_pilot_app = self.model.get_app("istio-pilot")
        gateway = self.model.relations["gateway"]

        if len(gateway) == 0:
            raise CheckFailedError("Missing required relation for gateway", BlockedStatus)

        try:
            data = gateway[0].data[istio_pilot_app]

            args = {
                **args,
                "gateway_name": data["gateway-name"],
                "gateway_namespace": data["gateway-namespace"],
            }
            return self.env.get_template("config.yaml.j2").render(**args)
        except Exception as error:
            self.log.error(
                "Encountered the following error when parsing gateway relation", f"{str(error)}"
            )
            raise CheckFailedError(
                "Unexpected error when parsing gateway relation data. See log", BlockedStatus
            )

    def _check_leader(self):
        if not self.unit.is_leader():
            # We can't do anything useful when not the leader, so do nothing.
            raise CheckFailedError("Waiting for leadership", WaitingStatus)

    def main(self, event):
        """Set up charm."""

        try:
            self._check_leader()

            self.log.info(f"Rendering charm for {event}")
            objs = self.render()
        except CheckFailedError as error:
            self.model.unit.status = error.status
            if isinstance(error.status_type, BlockedStatus):
                self.log.error(error.msg)
            else:
                self.log.info(error.msg)
            return

        self.log.info(f"Applying {len(objs)} objects")

        for obj in objs:
            try:
                self.apply(obj)
            except Exception as err:
                self.model.unit.status = BlockedStatus(f"Error installing charm: {err}")
                return

        self.model.unit.status = ActiveStatus()

    def remove(self, event):
        """Remove charm."""

        self.log.info(f"Rendering charm for {event}")

        objs = self.render()

        self.log.info(f"Removing {len(objs)} objects")

        for obj in objs:
            try:
                self.client.delete(type(obj), obj.metadata.name)
            except Exception as err:
                self.log.info(f"Error cleaning up: {err}")


class CheckFailedError(Exception):
    """Raise this exception if one of the checks in main fails."""

    def __init__(self, msg, status_type=None):
        super().__init__()

        self.msg = str(msg)
        self.status_type = status_type
        self.status = status_type(self.msg)


if __name__ == "__main__":
    main(Operator)
