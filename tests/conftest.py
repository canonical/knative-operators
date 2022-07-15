# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest

from lightkube import Client
from lightkube.generic_resource import create_namespaced_resource

KnativeService_v1 = create_namespaced_resource(
    group="serving.knative.dev",
    version="v1",
    kind="KantiveService",
    plural="knativeservices",
    verbs=None,
)

@pytest.fixture
async def lightkube_client():
    lightkube_client = Client(field_manager="test")
    yield lightkube_client
