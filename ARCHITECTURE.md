# Introduction

This document details the architecture of Charmed Knative

# Upstream

## Install

See instructions here for installing upstream Knative v1.1:

https://knative.dev/v1.1-docs/install/serving/install-serving-with-yaml/

Of note is this YAML file, which contains the core Knative components:

https://github.com/knative/serving/releases/download/v1.1.0/serving-core.yaml

## Charm Conversion

Each resource in that file has been mapped to one of the charms in this repository, with the
exception of the `*domain-mapping*` resources, which aren't necessary for an example app.

For example, the `secrets/webhook-certs` resource from that file is created by the
[operators/knative-webhoook][webhook] charm.

The `*domain-mapping*` resources will probably be necessary for a fully-featured Charmed Knative,
however.

[webhook]: operators/knative-webhook/src/webhooks.yaml.j2

Each charm listed here has an explanation of purpose here:

https://knative.dev/docs/serving/knative-kubernetes-services/#components

# Charmed

## Tests

CI isn't yet passing due to an issue with MetalLB, but tests can be run locally by bootstrapping
Juju onto MicroK8s `1.21/stable`, adding a `knative-serving` model, and then running

    KUBECONFIG=/path/to/kube/config tox -e integration -- --model=knative-serving

The need for setting the `KUBECONFIG` environment variable will go away when the integration tests
are converted to using `lightkube` instead of `kubectl`.

Note that you won't see pods for the example service before tests, or shortly after, as they're spun
up and taken down on demand due to the serverless nature Knative of.

# Notes

The charms are written using `lightkube`'s new `client.apply` functionality, which relies on
`ServerSideApply` functionality enabled on the cluster. They also have fallback to using
`client.create` and `client.patch` if `ServerSideApply` hasn't been enabled on the cluster. The
fallback was tested with setting `ServerSideApply=false` in
`/var/snap/microk8s/current/args/kubelet`.

`ServerSideApply` is very helpful with these charms however, as the workloads will actively maintain
some bits of some resources themselves. For example, the `knative-webhook` charm will create
`secrets/webhook-certs`, but the workload itself will set the `data` field. `ServerSideApply` will
enable Kubernetes itself to notice that the operator and workload are fighting over these fields.
With just `client.create` and `client.patch`, the fields will be silently overwritten. Another
example of where this happens is all of the webhooks created by the `knative-webhook` charm. The
`rules` field is managed by the workload, and should not be set by the operator itself.
