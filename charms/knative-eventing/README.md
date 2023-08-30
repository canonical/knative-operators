# `knative-eventing`

## Description
`knative-eventing` provides tools for routing events from producers to sinks, enabling developers to use an event-driven architecture with their applications.

## Usage

```
juju deploy knative-eventing --config namespace="knative-eventing" --trust
```
where:

* namespace: The namespace knative-eventing resources will be deployed into (it cannot be deployed into the same namespace as knative-operator or knative-serving

### Setting Custom Images for Knative Eventing

Knative deploys with a set of preconfigured images.  These images, listed in the [upstream documentation](https://knative.dev/docs/install/operator/configuring-eventing-cr/#download-images-from-different-repositories-without-secrets), can be overridden using the charm config `custom_images`.

For example:

images_to_override.yaml
```yaml
eventing-controller/eventing-controller: docker.io/knative-images-repo1/eventing-controller:latest
eventing-webhook/eventing-webhook: docker.io/knative-images-repo2/eventing-webhook:latest
```

```bash
juju config knative-eventing custom_images=@./images_to_override.yaml
```

For convenience, the default value for `custom_images` in [config.yaml](./config.yaml) lists all images, where an empty string in the dictionary means the default will be used.
