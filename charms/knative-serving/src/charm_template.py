# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path
from typing import List, Union, Optional

import jinja2
from jinja2 import Environment, FileSystemLoader
from lightkube import Client, codecs
from lightkube.core.exceptions import ApiError
from lightkube.core.resource import NamespacedResource, GlobalResource
from ops.charm import CharmBase
from ops.model import ActiveStatus, WaitingStatus, BlockedStatus, MaintenanceStatus

from charm_helpers.exceptions import ErrorWithStatus, LeadershipError
from lightkube_helpers import check_resources, get_first_worst_error


class ExtendedCharmBase(CharmBase):
    """An extended base class for Charms that includes some conveniences and basic features"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.log = logging.getLogger(__name__)
        self.app_name = self.model.app.name
        self.model_name = self.model.name

        self.framework.observe(self.on.config_changed, self.on_config_changed)
        self.framework.observe(self.on.install, self.on_install)
        self.framework.observe(self.on.leader_elected, self.on_leader_elected)
        self.framework.observe(self.on.remove, self.on_remove)
        self.framework.observe(self.on.upgrade_charm, self.on_upgrade_charm)
        self.framework.observe(self.on.update_status, self.on_update_status)

    def log_and_set_status(self, status: Union[ActiveStatus, WaitingStatus, BlockedStatus, MaintenanceStatus]):
        self.log.info(f"Setting unit status to: {str(status)}")
        self.unit.status = status

    def on_config_changed(self, _):
        raise NotImplementedError()

    def on_install(self, _):
        raise NotImplementedError()

    def on_leader_elected(self, _):
        raise NotImplementedError()

    def on_remove(self, event):
        raise NotImplementedError()

    def on_upgrade_charm(self, _):
        raise NotImplementedError()

    def on_update_status(self, _):
        raise NotImplementedError()


class KubernetesManifestCharmBase(ExtendedCharmBase):
    """A base charm for writing Kubernetes manifest charms

    A Kubernetes manifest charm is a charm that:
    *   derives its desired state by rendering one or more YAML templates, where these templates
        are filled using configuration from charm configuration, relations, and hard-coded sources
    *   deploys this desired state to Kubernetes via the Kubernetes API
    *   monitors and, if required, reconciles these objects to the desired state


    The default behaviours of this charm are described below for different events:

    Install:
    The Install event is handled by the `self.on_install()` method.  By default, this method will:
    * check if this unit is the leader, and set WaitingStatus if it is not
    * render the yaml templates listed in self.template_files, which are paths relative to
      self.manifests_dir
    * apply the rendered manifests to kubernetes using `self.reconcile`, which uses lightkube
    * Catch any errors during the above and raise the appropriate Status
    * If all works well, observe the charm workload's state in the cluster and, if ok, set status
      to Active

    Update-Status:
    The update-status event is handled by the `self.on_update_status()` method.  By default, this
    method will:
    * compute the charm's status using self.charm_status(), which does simple checks to ensure the
      k8s objects defined in manifests exist and that StatefulSets have their expected number of
      replicas
    * If status is not Active, emit a config_changed event that will try to reconcile the workload
      to get it Active

    Config Changed, Leader Elected, Upgrade Charm:
    By default, these events are handled like Install events using the `self.on_install()` handler


    To customize the behaviour of this base class, override the methods and attributes.  For
    example:
    * To add manifest files, append to or replace self.manifest_files in your charm `__init__`
    * To customize behaviour on install, config_changed, update_status, remove, or leader_elected,
      override the respective `self.on_*` method with your custom behaviour.  Look at this base
      class's on_install for a pattern you can extend
    * To customize how manifests are rendered across the entire charm, override or extend the
      `self.render_manifests()` method.  This modifies the canonical source of truth for how this
      base charm's methods (specifically self.charm_status(), self.on_install(), and
      self.reconcile())
    * To customize or extend how the charm assess its status, override self.charm_status().  This
      method is where a charm reflects at its resources or configuration and reports whether it is
      Active, and could be modified based on the specific charm (for example, you can assert
      the charm is active only if `some_k8s_object.status.IP!=None`
    * While this base charm automatically subscribes some base events (eg:
      `self.on_config_changed() is subscribed to the ConfigChanged event by default) and it is
      difficult to undo this, if you need to disable handling of a default event you can override
      the respective handler with `pass` and that will have nearly the same effect.  For example,
      you can use: `def on_config_changed(self, event): pass`
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

        # Properties
        self._jinja_env = None
        self._lightkube_client = None

    def charm_status(self, resources: Optional[List[Union[NamespacedResource, GlobalResource]]] = None) -> Union[ActiveStatus, WaitingStatus, BlockedStatus]:
        """Computes status of this charm based on the state of cluster objects, logging any errors
        """
        self.log.info("Computing status")

        try:
            self._check_leader()
        except LeadershipError as e:
            return e.status

        if resources is None:
            resources = self.render_manifests()

        charm_ok, errors = check_resources(self.lightkube_client, resources)
        if charm_ok:
            self.log.info("Status: active")
            status = ActiveStatus()
        else:
            # Hit one or more errors with resources.  Return status for worst and log all
            self.log.info("Charm is not active due to one or more issues:")

            # Log all errors, ignoring None's
            errors = [error for error in errors if error is not None]
            for i, error in enumerate(errors):
                self.log.info(f"Issue {i+1}/{len(errors)}: {error.msg}")

            # Return status based on the worst thing we encountered
            status = get_first_worst_error(errors).status

        return status

    def _check_leader(self):
        if not self.unit.is_leader():
            # We can't do anything useful when not the leader, so do nothing.
            raise LeadershipError()

    def on_config_changed(self, event):
        self.on_install(event)

    def on_install(self, event):
        """Installs all objects, checking and setting status at the end of install"""
        self.unit.status = MaintenanceStatus("Deploying resources to cluster")
        try:
            self._check_leader()
            resources = self.render_manifests()
            self.reconcile(resources)
        except ErrorWithStatus as e:
            self.log_and_set_status(e.status)
            return

        self.log_and_set_status(self.charm_status(resources))

    def on_leader_elected(self, event):
        self.on_install(event)

    def on_remove(self, _):
        """Remove all objects from the cluster

        By default, this should be implicitly handled by Juju and specific resource removal should
        not be necessary, but in some situations that is not the case.  Override this method with
        custom removal logic if required.
        """
        self.log.info("Removal hook fired but no custom removal actions taken - exiting on_remove")
        pass

    def on_upgrade_charm(self, event):
        self.on_install(event)

    def on_update_status(self, event):
        charm_status = self.charm_status()
        if not isinstance(charm_status, ActiveStatus):
            # Queue an install event to try to reconcile our resources
            self.log.info("Charm emitting an install event to try to reconcile resources")
        self.on.config_changed.emit()
        self.log_and_set_status(charm_status)

    def reconcile(self, resources: Optional[List[Union[NamespacedResource, GlobalResource]]] = None):
        """Reconcile our Kubernetes objects to achieve the desired state

        This can be invoked to both install or update objects in the cluster.  It uses an apply
        logic to update things only if necessary.  This method by default __does not__ remove
        objects that are no longer required - if handling that situation is required, it must be
        done separately.
        """
        self.log.info("Reconciling")
        if resources is None:
            resources = self.render_manifests()
        self.log.debug(f"Applying {len(resources)} resources")

        try:
            self.lightkube_client.apply_many(resources)
        except ApiError as e:
            # Handle fobidden error as this likely means we do not have --trust
            if e.status.code == 403:
                self.logger.error(
                    "Received Forbidden (403) error from lightkube when creating resources.  "
                    "This may be due to the charm lacking permissions to create cluster-scoped "
                    "roles and resources.  Charm must be deployed with `--trust`"
                )
                self.logger.error(f"Error received: {str(e)}")
                raise ReconcileError("Cannot create required resources.  Charm may be missing `--trust`", BlockedStatus)
            else:
                raise e
        self.log.info("Reconcile completed successfully")

    def render_manifests(self) -> List[Union[NamespacedResource, GlobalResource]]:
        """Renders this charm's manifests, returning them as a list of Lightkube Resources

        If overriding this class, you should replace it with a method that will always generate
        a list of all resources that should currently exist in the cluster.
        """
        self.log.info("Rendering manifests")
        self.log.debug(f"Rendering with context: {self.context_for_render}")
        manifest_parts = []
        for template_file in self.template_files:
            self.log.debug(f"Rendering manifest for {template_file}")
            template = self.jinja_env.get_template(template_file)
            rendered_template = template.render(**self.context_for_render)
            manifest_parts.append(rendered_template)
            self.log.debug(f"Rendered manifest:\n{manifest_parts[-1]}")
        return codecs.load_all_yaml("\n---\n".join(manifest_parts))

    @property
    def jinja_env(self) -> Environment:
        if self._jinja_env is None:
            self._jinja_env = Environment(
                loader=FileSystemLoader(str(self.manifests_dir))
            )
        return self._jinja_env

    @jinja_env.setter
    def jinja_env(self, value: Environment):
        if isinstance(value, jinja2.Environment):
            self._jinja_env = value
        else:
            raise ValueError("jinja_env must be a jinja2.Environment")

    @property
    def lightkube_client(self) -> Client:
        if self._lightkube_client is None:
            self._lightkube_client = Client(field_manager=self.app_name)
        return self._lightkube_client

    @lightkube_client.setter
    def lightkube_client(self, value: Client):
        if isinstance(value, Client):
            self._lightkube_client = value
        else:
            raise ValueError("lightkube_client must be a lightkube.Client")

    @property
    def context_for_render(self):
        """Returns the context used for rendering the templates during self.render_manifest()

        Override this property to provide additional custom context.  Raising ErrorWithStatus
        Exceptions here will cause the charm to enter the specified status.
        """
        return {
            "app_name": self.app_name,
            "model_name": self.model_name,
        }



class ReconcileError(ErrorWithStatus):
    pass
