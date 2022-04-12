#!/usr/bin/env python3

import logging

from jinja2 import Environment, FileSystemLoader
from lightkube import ApiError, Client, codecs
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus

from lightkube.generic_resource import create_namespaced_resource

class Operator(CharmBase):
    """Charmed Operator."""

    def __init__(self, *args):
        super().__init__(*args)

        self.log = logging.getLogger(__name__)
        self.client = Client(field_manager=f"{self.model.name}-{self.model.app.name}")

        for event in [
            self.on.install,
            self.on.leader_elected,
            self.on.upgrade_charm,
            self.on.config_changed,
            self.on.update_status,
        ]:
            self.framework.observe(event, self.main)

        self.framework.observe(self.on.remove, self.remove)

    def apply(self, obj):
        try:
            self.client.apply(obj)
        except ApiError as err:
            if err.status.code != 415:
                raise

        self.log.info(f"Got 415 response while applying {obj}, assuming ServerSideApply=false")

        try:
            self.client.create(obj)
        except ApiError as err:
            if err.status.code != 409:
                raise

        #self.client.patch(type(obj), obj.metadata.name, obj)

    def render(self):
        env = Environment(
            loader=FileSystemLoader("src/"),
            variable_start_string="[[",
            variable_end_string="]]",
        )
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
        args = {"name": "activator", "namespace": self.model.name, "knative_serving": "knative-serving"}
        deployment = env.get_template("deployment.yaml.j2").render(**args)
        config = env.get_template("config.yaml.j2").render(**args)
        rbac = env.get_template("rbac.yaml.j2").render(**args)
        gateway = env.get_template("gateway.yaml.j2").render(**args)
        peer_auth = env.get_template("peer_auth.yaml.j2").render(**args)

        return codecs.load_all_yaml("\n---\n".join([gateway, peer_auth, rbac, deployment, config]))

    def main(self, event):
        """Set up charm."""

        self.log.info(f"Rendering charm for {event}")

        objs = self.render()

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


if __name__ == "__main__":
    main(Operator)