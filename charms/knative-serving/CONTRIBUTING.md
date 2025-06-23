# Contributing

## Overview

This documents explains the processes and practices recommended for contributing enhancements to
this operator.

- Generally, before developing enhancements to this charm, you should consider [opening an issue
  ](https://github.com/canonical/knative-operators/issues) explaining your use case.
- If you would like to chat with us about your use-cases or proposed implementation, you can reach
  us at [Canonical Mattermost public channel](https://chat.charmhub.io/charmhub/channels/charm-dev)
  or [Discourse](https://discourse.charmhub.io/).
- Familiarising yourself with the [Charmed Operator Framework](https://juju.is/docs/sdk) library
  will help you a lot when working on new features or bug fixes.
- All enhancements require review before being merged. Code review typically examines
  - code quality
  - test coverage
  - user experience for Juju administrators this charm.
- Please help us out in ensuring easy to review branches by rebasing your pull request branch onto
  the `main` branch. This also avoids merge commits and creates a linear Git commit history.

## Developing

You can use the environments created by `tox` for development:

```shell
tox --notest -e unit
source .tox/unit/bin/activate
```

### Testing

```shell
tox -e fmt           # update your code according to linting rules
tox -e lint          # code style
tox -e unit          # unit tests
tox -e integration   # integration tests
tox                  # runs 'lint' and 'unit' environments
```

## Build charm

Build the charm in this git repository using:

```shell
charmcraft pack
```

### Deploy

```bash
# Create a model
MODEL_NAME="dev"
DEFAULT_GATEWAY="knative-gateway"
juju add-model ${MODEL_NAME}
# Deploy dependencies
juju deploy istio-pilot --config default-gateway=${DEFAULT_GATEWAY} --trust
juju deploy istio-gateway istio-ingressgateway --config kind="ingress" --trust
juju relate istio-pilot istio-ingressgateway
# Enable DEBUG logging
juju model-config logging-config="<root>=INFO;unit=DEBUG"
# Deploy the charm
juju deploy ./knative-serving_ubuntu@24.04-amd64.charm \
    --config namespace="knative-serving" --config istio.gateway.namespace=${MODEL_NAME} \
    --config istio.gateway.name=${DEFAULT_GATEWAY} --trust
```

where:

* namespace: The namespace knative-serving resources will be deployed into (it cannot be deployed into the same namespace as knative-operator or knative-eventing)
* istio.gateway.namespace: The namespace the Istio gateway is deployed to (generally, the model that Istio is deployed to).
* istio.gateway.name: The name of the Istio gateway
## Canonical Contributor Agreement

Canonical welcomes contributions to the charmed knative-serving. Please check out our [contributor agreement](https://ubuntu.com/legal/contributors) if you're interested in contributing to the solution.
