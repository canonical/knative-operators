#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library for sharing knative-serving localGateway and default gateway information.

This library provides a Python API for providing and requesting information about
knative-serving's localGateway and the model's default gateway that the knative-serving
charm obtains from its own configuration.

## Getting started

### Fetching the library

Using charmcraft you can:
`charmcraft fetch charms.knative_serving.v0.knative_serving_localgateway_info`

### Adding the knative-serving: localgateway-info relation
You can add the relation in the 'requires' section in `metadata.yaml`:
```yaml
requires:
    knative-serving-networking:
      interface: localgateway-info
      limit: 1
```

### Instantiate the library as "provider"

```python
from charms.knative_serving.v0.knative_serving_localgateway_info import LocalGatewayProvider, LocalGatewayRelationError

class ProviderCharm(self):
    def __init__(self, *args, **kwargs):
        ...
        self.localgateway_provider = LocalGatewayProvider(self)
        self.observe(self.on.some_event, self._some_event_handler)

    def _some_event_handler(self, ...):
        # This will update the relation data bag with the localGateway name and namespace
        try:
            self.localgateway_provider.send_localgateway_data(charm, localgateway_name, localgateway_namespace)
        except LocalGatewayRelationError as e:
            raise <your preferred exception with a message> from e
```

### Instantiate the library as "requirer"

```python
from charms.knative_serving.v0.knative_serving_localgateway_info import LocalGatewayRequirer, LocalGatewayRelationError

class RequirerCharm(self):
    def __init__(self, *args, **kwargs):
        ...
        self.localgateway_requirer = LocalGatewayRequirer(self)
        self.observe(self.on.some_event, self._some_event_handler)

    def _some_event_handler(self, ...):
        # This will get the relation data bag with the localGateway name and namespace info
        try:
            self.localgateway_provider.get_localgateway_data(charm, localgateway_name, localgateway_namespace)
        except LocalGatewayRelationError as e:
            raise <your preferred exception with a message> from e
```
"""

import logging
from ops.framework import Object
from ops.model import Application, Model

# The unique Charmhub library identifier, never change it
LIBID = "558a3ed7a672442d803cdc122cf8b561"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

# The relation name and interface should be the same in the requirer and provider
# This value is configured in metadata.yaml
RELATION_INTERFACE = "localgateway-info"
RELATION_NAME = "knative-serving-networking"

logger = logging.getLogger(__name__)


class KnativeServingNetworkingRelationError(Exception):
    pass


class KnativeServingNetworkingRelationMissingError(KnativeServingNetworkingRelationError):
    def __init__(self):
        self.message = "Missing knative-serving-networking relation with knative-serving"
        super().__init__(self.message)


class KnativeServingNetworkingRelationDataMissingError(KnativeServingNetworkingRelationError):
    def __init__(self):
        self.message = "There is no data in the relation data bag or there's missing data"
        super().__init__(self.message)


def knative_serving_networking_relation_preflight_check(
    model: Model, relation_name: str, requirer: bool = False
) -> None:
    """Series of checks for ensuring the knative-serving-networking relation is properly established.

    Args:
        model (Model): the juju model as seen by the provider/requirer unit
        relation_name (str): the name of the relation

    Raises:
        KnativeServingNetworkingRelationMissingError when there is no relation between two units
        KnativeServingNetworkingRelationDataMissingError when there is no data in the data bag
    """
    knative_serving_networking_relation = model.get_relation[relation_name]

    if not knative_serving_networking_relation:
        raise KnativeServingNetworkingRelationMissingError()

    if requirer and not knative_serving_networking_relation.data:
        raise KnativeServingNetworkingRelationDataMissingError()


class LocalGatewayProvier(Object):
    """Base class that represents a "provider" relation end.

    Args:
        provider_charm (Application): the provider application
        relation_name (str): the name of the relation

    Attributes:
        provider_charm (Application): variable for storing the provider application
        relation_name (str): variable for storing the name of the relation
    """

    def __init__(self, provider_charm: Application, relation_name: str = RELATION_NAME):
        super().__init__(provider_charm, relation_name)

    def send_localgateway_data(self, localgateway_name: str, localgateway_namespace: str) -> None:
        """Updates the relation data bag with data from the localGateway.

        Args:
            provider_charm (Application): the provider application, most likely knative-serving
            localgateway_name (str): the name of the localGateway created by knative-serving
            localgateway_namespace(str): the namespace of the localGateway created by knative-serving

        Raises:
        """
        # Run pre-flight checks to ensure the relation is set correctly
        knative_serving_networking_relation_preflight_check(
            model=self.model, relation_name=self.relation_name
        )

        # Update the relation data bag with localgateway information
        knative_serving_networking_relations = self.model.get_relation[self.relation_name]
        for relation in knative_serving_networking_relations:
            relation.data[self.provider_charm].update(
                {
                    "localgateway_name": localgateway_name,
                    "localgateway_namespace": localgateway_namespace,
                }
            )


class LocalGatewayRequirer(Object):
    """Base class that represents a "requirer" relation end.

    Args:
        requirer_charm (Application): the requirer application
        relation_name (str): the name of the relation

    Attributes:
        requirer_charm (Application): variable for storing the requirer application
        relation_name (str): variable for storing the name of the relation
    """

    def __init__(self, requirer_charm: Application, relation_name: str = RELATION_NAME):
        super.__init__(requirer_charm, relation_name)

    def get_localgateway_data(self) -> Dict:
        """Returns a dictionary with the localGateway information.

        Raises:
            KnativeServingNetworkingRelationDataMissingError: if data is missing attributes
        """
        # Do nothing if the unit is not leader
        if not self.model.unit.is_leader():
            logger.info("This unit is not leader, no action will be taken.")
            return
        # Run pre-flight checks to ensure the relation is set correctly
        knative_serving_networking_relation_preflight_check(
            model=self.model, relation_name=self.relation_name, requirer=True
        )

        # This charm should only establish a relation with exactly one unit
        # the following extracts exactly one unit from the set that's
        # returned by mysql_relation.data
        knative_serving_networking_relation = self.model.get_relation(self.relation_name)
        remote_units = knative_serving_networking_relation.units
        knative_serving_unit = list(remote_units)[0]

        # Get knative_serving_networking data
        knative_serving_networking_data = knative_serving_networking_relation.data[
            knative_serving_unit
        ]

        # Check if the relation data contains the expected attributes
        expected_attributes = ["localgateway_name", "localgateway_namespace"]
        missing_attributes = [
            attribute
            for attribute in expected_attributes
            if attribute not in knative_serving_networking_data
        ]

        if missing_attributes:
            raise KnativeServingNetworkingRelationDataMissingError()
        return knative_serving_networking_data
