# `knative-serving`

## Description

`knative-serving` provides components that enable rapid deployment of serverless containers, autoscaling (including down to zero), support for multiple layers, and revision tracking.

## Usage

```
juju deploy knative-serving --config namespace="knative-serving" --config istio.gateway.namespace=${MODEL_NAME} --config istio.gateway.name=${DEFAULT_GATEWAY} --trust
```

where:

* namespace: The namespace knative-serving resources will be deployed into (it cannot be deployed into the same namespace as knative-operator or knative-eventing
* istio.gateway.namespace: The namespace the Istio gateway is deployed to (generally, the model that Istio is deployed to).
* istio.gateway.name: The name of the Istio gateway

### Setting Custom Images for Knative Serving

Knative deploys with a set of preconfigured images.  These images, listed in the [upstream documentation](https://knative.dev/docs/install/operator/configuring-serving-cr/#download-images-individually-without-secrets), can be overridden using the charm config `custom_images`.

For example:

images_to_override.yaml
```yaml
activator: 'my.repo/my-activator:latest'
controller: 'my.repo/my-controller:v1.2.3'
```

```bash
juju config knative-serving custom_images=@./images_to_override.yaml
```

For convenience, the default value for `custom_images` in [config.yaml](./config.yaml) lists all images, where an empty string in the dictionary means the default will be used.
