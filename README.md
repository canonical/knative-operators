# Charmed Knative Operators

Knative is a Kubernetes-based platform to deploy and manage modern serverless workloads.

For more details of what is possible with Knative, see https://knative.dev/

## Usage

### Pre-requisites

Microk8s 1.21/stable
>NOTE: These instructions assume you have run `microk8s enable dns storage rbac metallb:"10.64.140.43-10.64.140.49,192.168.0.105-192.168.0.111"`

### Add a model and set variables

```
MODEL_NAME="knative"
DEFAULT_GATEWAY="knative-gateway"
juju add-model ${MODEL_NAME}
```

### Deploy dependencies

Knative (in particular `knative-serving`) requires `istio-operators` to be deployed in the model. To correctly configure them, you can:

```
ISTIO_CHANNEL=1.11/stable
juju deploy istio-pilot --config default-gateway=${DEFAULT_GATEWAY} --channel ${ISTIO_CHANNEL} --trust
juju deploy istio-gateway istio-ingressgateway --config kind="ingress" --channel ${ISTIO_CHANNEL} --trust
juju relate istio-pilot istio-ingressgateway
```

### `knative-operator`

The `knative-operator` is responsible for installing, configuring, and managing the `serving` and `eventing` components. You must deploy the charmed `knative-operator` before any other Knative component.

```
KNATIVE_CHANNEL=1.1/edge
juju deploy knative-operator --trust --channel ${KNATIVE_CHANNEL}
```

### `knative-serving`

`knative-serving` provides components that enable rapid deployment of serverless containers, autoscaling (including down to zero), support for multiple layers, and revision tracking. Charmed `knative-serving` can be deployed as follows:

```
juju deploy knative-serving --config namespace="knative-serving" --config istio.gateway.namespace=${MODEL_NAME} --config istio.gateway.name=${DEFAULT_GATEWAY} --channel ${KNATIVE_CHANNEL} --trust
```

where:

* namespace: The namespace knative-serving resources will be deployed into (it cannot be deployed into the same namespace as knative-operator or knative-eventing
* istio.gateway.namespace: The namespace the Istio gateway is deployed to (generally, the model that Istio is deployed to).
* istio.gateway.name: The name of the Istio gateway

### `knative-eventing`

`knative-eventing` provides tools for routing events from producers to sinks, enabling developers to use an event-driven architecture with their applications. Charmed `knative-eventing` can be deployed as follows:

```
juju deploy knative-eventing --config namespace="knative-eventing" --channel ${KNATIVE_CHANNEL} --trust
```
where:

* namespace: The namespace knative-eventing resources will be deployed into (it cannot be deployed into the same namespace as knative-operator or knative-serving

## Collecting metrics

Metrics are collected by an OpenTelemetry collector managed by the `knative-operator`, which is then scraped by `prometheus-k8s`. Please follow these instructions to enable metrics collection for `knative-eventing` and `knative-serving`.

1. Deploy `prometheus-k8s` and relate to `knative-operator`

```bash
juju deploy prometheus-k8s --trust
juju relate prometheus-k8s:metrics-endpoint knative-operator:metrics-endpoint
```

2. Enable metric collection for `knative-<eventing/serving>`

```bash
juju relate knative-<eventing/serving>:otel-collector knative-operator:otel-collector
```

3. Wait for everything to be active and idle

4. You can now [access the Prometheus dashboard](https://github.com/canonical/prometheus-k8s-operator#dashboard) to have access to the collected metrics. Alternatively, you could send GET requests to the OpenTelemetry metrics exporter directly using the `otel-export` `Service`, for example:

```bash
curl <otel-exporter service>:8889/metrics
```

Please refer to [Collecting Metrics in Knative](https://knative.dev/docs/eventing/observability/metrics/collecting-metrics/) for more information.

## Integration example

To run a simple example that integrates both `eventing` and `serving`, you can run the one provided in `examples/`.

> NOTE: this example is based on [Using a Knative Service as a source](https://knative.dev/docs/getting-started/first-source/#sending-an-event)

1. Create the `cloudevents-player` Knative Service

```
kubectl apply -f examples/cloudevents-player.yaml
```

2. Get the LOADBALANCER_IP

```
LOADBALANCER_IP=$(kubectl get svc istio-ingressgateway-workload -n${MODEL_NAME} -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
```

3. Send an event

```
curl -i http://cloudevents-player.default.${LOADBALANCER_IP}.nip.io
    -H "Content-Type: application/json"
    -H "Ce-Id: 123456789"
    -H "Ce-Specversion: 1.0"
    -H "Ce-Type: some-type"
    -H "Ce-Source: command-line"
    -d '{"msg":"Hello CloudEvents!"}'
```

Expected output:

```
HTTP/1.1 202 Accepted
content-length: 0
date: Mon, 27 Jun 2022 19:05:02 GMT
x-envoy-upstream-service-time: 5
server: istio-envoy
```

4. View events

```
curl http://cloudevents-player.default.${LOADBALANCER_IP}.nip.io
```

Expected output:

```
[{"event":{"attributes":{"datacontenttype":"application/json","id":"123456789","mediaType":"application/json","source":"command-line","specversion":"1.0","type":"some-type"},"data":{"msg":"Hello CloudEvents!"},"extensions":{}},"id":"123456789","receivedAt":"2022-06-27T21:05:02.443545+02:00[Europe/Madrid]","type":"RECEIVED"},{"event":{"attributes":{"datacontenttype":"application/json","id":"123456789","mediaType":"application/json","source":"command-line","specversion":"1.0","type":"some-type"},"data":{"msg":"Hello CloudEvents!"},"extensions":{}},"id":"123456789","receivedAt":"2022-06-27T20:51:41.100145+02:00[Europe/Madrid]","type":"RECEIVED"}]
```
