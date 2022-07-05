# `knative-eventing`

## Description
`knative-eventing` provides tools for routing events from producers to sinks, enabling developers to use an event-driven architecture with their applications.

## Usage

```
juju deploy knative-eventing --config namespace="knative-eventing" --trust
```
where:

* namespace: The namespace knative-eventing resources will be deployed into (it cannot be deployed into the same namespace as knative-operator or knative-serving
