#!/usr/bin/env python3

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from lightkube import ApiError, Client, codecs
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus


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

        self.client.patch(type(obj), obj.metadata.name, obj)

    def render(self):
        env = Environment(
            loader=FileSystemLoader("src/"),
            variable_start_string="[[",
            variable_end_string="]]",
        )

        args = {"name": "controller", "namespace": self.model.name}
        crds = Path("src/crds.yaml").read_text()
        rbac = env.get_template("rbac.yaml.j2").render(**args)
        deployment = env.get_template("deployment.yaml.j2").render(**args)
        config = env.get_template("config.yaml.j2").render(**args)
        # images = env.get_template("images.yaml.j2").render(**args)

        return codecs.load_all_yaml("\n---\n".join([crds, rbac, deployment, config]))

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
