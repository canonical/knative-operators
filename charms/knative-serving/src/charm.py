#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


from charm_template import KubernetesManifestCharmBase
from ops.main import main

from lightkube_custom_resources.operator import KnativeServing_v1alpha1

class KnativeServingCharm(KubernetesManifestCharmBase):
    """A charm for creating Knative Serving instances via the Knative Operator"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.template_files = [
            "KnativeServing.yaml.j2",
        ]


if __name__ == "__main__":
    main(KnativeServingCharm)
