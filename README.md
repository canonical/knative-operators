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
juju deploy istio-pilot --config default-gateway=${DEFAULT_GATEWAY} --trust
juju deploy istio-gateway istio-ingressgateway --config kind="ingress" --trust
juju relate istio-pilot istio-ingressgateway
```

### `knative-operator`

The `knative-operator` is responsible for installing, configuring, and managing the `serving` and `eventing` components. Despite your final application, you must deploy the charmed `knative-operator` before any other Knative component.

```
juju deploy knative-operator --trust
```

### `knative-serving`

`knative-serving` provides components that enable rapid deployment of serverless containers, autoscaling (including down to zero), support for multiple layers, and revision tracking. Charmed `knative-serving` can be deployed as follows:

```
juju deploy knative-serving --config namespace="knative-serving" --config istio.gateway.namespace=${MODEL_NAME} --trust
```

### `knative-eventing`

`knative-eventing` provides tools for routing events from producers to sinks, enabling developers to use an event-driven architecture with their applications. Charmed `knative-eventing` can be deployed as follows:

```
juju deploy knative-eventing --config namespace="knative-eventing" --trust
```

## Integration example

To run an simple example that integrates both `eventing` and `serving`, you can run the one provided in `examples/`.

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
