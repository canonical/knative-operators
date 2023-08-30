#!/bin/bash
#
# This script returns list of container images that are managed by this charm and/or its workload
#
# static list
STATIC_IMAGE_LIST=(
# manual addition based on https://github.com/canonical/knative-operators/issues/137
gcr.io/knative-releases/knative.dev/eventing/cmd/broker/filter@sha256:33ea8a657b974d7bf3d94c0b601a4fc287c1fb33430b3dda028a1a189e3d9526
gcr.io/knative-releases/knative.dev/eventing/cmd/broker/ingress@sha256:f4a9dfce9eec5272c90a19dbdf791fffc98bc5a6649ee85cb8a29bd5145635b1
gcr.io/knative-releases/knative.dev/eventing/cmd/controller@sha256:cbc452f35842cc8a78240642adc1ebb11a4c4d7c143c8277edb49012f6cfc5d3
gcr.io/knative-releases/knative.dev/eventing/cmd/in_memory/channel_controller@sha256:3ced549336c7ccf3bb2adf23a558eb55bd1aec7be17837062d21c749dfce8ce5
gcr.io/knative-releases/knative.dev/eventing/cmd/in_memory/channel_dispatcher@sha256:e17bbdf951868359424cd0a0465da8ef44c66ba7111292444ce555c83e280f1a
gcr.io/knative-releases/knative.dev/eventing/cmd/mtchannel_broker@sha256:c5d3664780b394f6d3e546eb94c972965fbd9357da5e442c66455db7ca94124c
gcr.io/knative-releases/knative.dev/eventing/cmd/webhook@sha256:c9c582f530155d22c01b43957ae0dba549b1cc903f77ec6cc1acb9ae9085be62
gcr.io/knative-releases/knative.dev/net-istio/cmd/controller@sha256:2b484d982ef1a5d6ff93c46d3e45f51c2605c2e3ed766e20247d1727eb5ce918
gcr.io/knative-releases/knative.dev/net-istio/cmd/webhook@sha256:59b6a46d3b55a03507c76a3afe8a4ee5f1a38f1130fd3d65c9fe57fff583fa8d
gcr.io/knative-releases/knative.dev/pkg/apiextensions/storageversion/cmd/migrate@sha256:59431cf8337532edcd9a4bcd030591866cc867f13bee875d81757c960a53668d
gcr.io/knative-releases/knative.dev/pkg/apiextensions/storageversion/cmd/migrate@sha256:d0095787bc1687e2d8180b36a66997733a52f8c49c3e7751f067813e3fb54b66
)
# dynamic list
IMAGE_LIST=()
IMAGE_LIST+=($(find . -type f -name metadata.yaml -exec yq '.resources | to_entries | .[] | .value | ."upstream-source"' {} \;))
IMAGE_LIST+=($(grep image charms/knative-operator/src/manifests/observability/collector.yaml.j2 | awk '{print $2}' | sort --unique))
# obtaint knative serving version and corresponding knative release information
KNATIVE_SERVING_VERSION=$(yq '.options.version.default' ./charms/knative-serving/config.yaml)
KNATIVE_REPO_DOWNLOAD_URL=https://github.com/knative/serving/releases/download/
wget -q "${KNATIVE_REPO_DOWNLOAD_URL}/knative-v${KNATIVE_SERVING_VERSION}/serving-core.yaml"
SERVING_IMAGE_LIST=()
SERVING_IMAGE_LIST+=($(yq 'select(di == 28) | .spec.image' ./serving-core.yaml))
SERVING_IMAGE_LIST+=($(yq 'select(di == 31) | .data.queue-sidecar-image' ./serving-core.yaml))
SERVING_IMAGE_LIST+=($(yq -N 'select(di > 31) | .spec.template.spec.containers | .[] | .image' ./serving-core.yaml))
wget -q "${KNATIVE_REPO_DOWNLOAD_URL}/knative-v${KNATIVE_SERVING_VERSION}/serving-hpa.yaml"
SERVING_IMAGE_LIST+=($(yq 'select(di == 0) | .spec.template.spec.containers | .[] | .image' ./serving-hpa.yaml))
wget -q "${KNATIVE_REPO_DOWNLOAD_URL}/knative-v${KNATIVE_SERVING_VERSION}/serving-default-domain.yaml"
SERVING_IMAGE_LIST+=($(yq 'select(di == 0) | .spec.template.spec.containers | .[] | .image' ./serving-default-domain.yaml))
printf "%s\n" "${SERVING_IMAGE_LIST[@]}"
printf "%s\n" "${STATIC_IMAGE_LIST[@]}"
printf "%s\n" "${IMAGE_LIST[@]}"
