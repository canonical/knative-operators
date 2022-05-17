# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import jinja2
from jinja2 import Environment, FileSystemLoader
from lightkube import Client, codecs
from ops.charm import CharmBase


class ExtendedCharmBase(CharmBase):
    """An extended base class for Charms that includes some conveniences and basic features"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.log = logging.getLogger(__name__)
        self.name = self.model.app.name
        self.model_name = self.model.name

        for event in [
            self.on.install,
            self.on.leader_elected,
            self.on.upgrade_charm,
            self.on.config_changed,
            self.on.update_status,
        ]:
            self.framework.observe(event, self.reconcile)

        self.framework.observe(self.on.remove, self.on_remove)

    def reconcile(self, event):
        raise NotImplementedError()

    def on_remove(self, event):
        raise NotImplementedError()


class KubernetesManifestCharmBase(ExtendedCharmBase):
    """A base charm for writing Kubernetes manifest charms

    A Kubernetes manifest charm is a charm that:
    *   derives its desired state by rendering one or more YAML templates, where these templates
        are filled using configuration from charm configuration, relations, and hard-coded sources
    *   deploys this desired state to Kubernetes via the Kubernetes API
    *   monitors and, if required, reconciles these objects to the desired state
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.src_dir = Path("src")
        self.manifests_dir = self.src_dir / "manifests"

        # template_files are relative to the directory used by the jinva Environment.  By default,
        # this is the self.manifests_dir
        self.template_files = [
            "manifests.yaml.j2",
        ]

        # Context used for rendering the templates using the default self.render().  Add
        # additional state here as required, over override entirely
        self.context_for_render = {
            "charm_name": self.name,
            "model_name": self.model_name,
        }

        self._jinja_env = None

    def reconcile(self, event):
        """Reconcile our Kubernetes objects to achieve the desired state

        This can be invoked to both install or update objects in the cluster.  It uses an apply
        logic to update things only if necessary
        """

        raise NotImplementedError()

    def render_manifests(self):
        self.log.info(f"Rendering manifests")
        self.log.debug(f"Rendering with context: {self.context_for_render}")
        manifest_parts = []
        for template_file in self.template_files:
            self.log.debug(f"Rendering manifest for {template_file}")
            manifest_parts.append(self.jinja_env.get_template(template_file).render(**self.context_for_render))
            self.log.debug(f"Rendered manifest:\n{manifest_parts[-1]}")
        return codecs.load_all_yaml("\n---\n".join(manifest_parts))

    @property
    def jinja_env(self):
        if self._jinja_env:
            return self._jinja_env
        else:
            self._jinja_env = Environment(
                loader=FileSystemLoader(str(self.manifests_dir))
            )
            return self._jinja_env

    @jinja_env.setter
    def jinja_env(self, value):
        if isinstance(value, jinja2.Environment):
            self._jinja_env = value
        else:
            raise ValueError("jinja_env must be a jinja2.Environment")
