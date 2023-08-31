#!/bin/bash
#
# This script returns list of container images that are managed by this charm and/or its workload
#
# static list
STATIC_IMAGE_LIST=(
# manual addition based on https://github.com/canonical/knative-operators/issues/137
# TO-DO: This images are present in deployment, but either cannot be found in YAMLs and/or their SHA do not match the deployed versions
gcr.io/knative-releases/knative.dev/net-istio/cmd/controller@sha256:2b484d982ef1a5d6ff93c46d3e45f51c2605c2e3ed766e20247d1727eb5ce918
gcr.io/knative-releases/knative.dev/net-istio/cmd/webhook@sha256:59b6a46d3b55a03507c76a3afe8a4ee5f1a38f1130fd3d65c9fe57fff583fa8d
gcr.io/knative-releases/knative.dev/pkg/apiextensions/storageversion/cmd/migrate@sha256:59431cf8337532edcd9a4bcd030591866cc867f13bee875d81757c960a53668d
gcr.io/knative-releases/knative.dev/pkg/apiextensions/storageversion/cmd/migrate@sha256:d0095787bc1687e2d8180b36a66997733a52f8c49c3e7751f067813e3fb54b66
)
# dynamic list
IMAGE_LIST=()
IMAGE_LIST+=($(find . -type f -name metadata.yaml -exec yq '.resources | to_entries | .[] | .value | ."upstream-source"' {} \;))
IMAGE_LIST+=($(grep image charms/knative-operator/src/manifests/observability/collector.yaml.j2 | awk '{print $2}' | sort --unique))
# obtain knatice eventing version and corresponding knative release information
KNATIVE_EVENTING_VERSION=$(yq '.options.version.default' ./charms/knative-eventing/config.yaml)
KNATIVE_EVENTING_REPO_DOWNLOAD_URL=https://github.com/knative/eventing/releases/download/
EVENTING_IMAGE_LIST=()
wget -q "${KNATIVE_EVENTING_REPO_DOWNLOAD_URL}/knative-v${KNATIVE_EVENTING_VERSION}/eventing-core.yaml"
EVENTING_IMAGE_LIST+=($(yq -N '.spec.template.spec.containers | .[] | .image' ./eventing-core.yaml))
wget -q "${KNATIVE_EVENTING_REPO_DOWNLOAD_URL}/knative-v${KNATIVE_EVENTING_VERSION}/eventing.yaml"
EVENTING_IMAGE_LIST+=($(yq -N '.spec.template.spec.containers | .[] | .image' ./eventing.yaml))
# obtain knative serving version and corresponding knative release information
KNATIVE_SERVING_VERSION=$(yq '.options.version.default' ./charms/knative-serving/config.yaml)
KNATIVE_SERVING_REPO_DOWNLOAD_URL=https://github.com/knative/serving/releases/download/
SERVING_IMAGE_LIST=()
wget -q "${KNATIVE_SERVING_REPO_DOWNLOAD_URL}/knative-v${KNATIVE_SERVING_VERSION}/serving-core.yaml"
SERVING_IMAGE_LIST+=($(yq 'select(di == 28) | .spec.image' ./serving-core.yaml))
SERVING_IMAGE_LIST+=($(yq 'select(di == 31) | .data.queue-sidecar-image' ./serving-core.yaml))
SERVING_IMAGE_LIST+=($(yq -N 'select(di > 31) | .spec.template.spec.containers | .[] | .image' ./serving-core.yaml))
wget -q "${KNATIVE_SERVING_REPO_DOWNLOAD_URL}/knative-v${KNATIVE_SERVING_VERSION}/serving-hpa.yaml"
SERVING_IMAGE_LIST+=($(yq 'select(di == 0) | .spec.template.spec.containers | .[] | .image' ./serving-hpa.yaml))
wget -q "${KNATIVE_SERVING_REPO_DOWNLOAD_URL}/knative-v${KNATIVE_SERVING_VERSION}/serving-default-domain.yaml"
SERVING_IMAGE_LIST+=($(yq 'select(di == 0) | .spec.template.spec.containers | .[] | .image' ./serving-default-domain.yaml))
wget -q "${KNATIVE_SERVING_REPO_DOWNLOAD_URL}/knative-v${KNATIVE_SERVING_VERSION}/serving-storage-version-migration.yaml"
SERVING_IMAGE_LIST+=($(yq 'select(di == 0) | .spec.template.spec.containers | .[] | .image' ./serving-storage-version-migration.yaml))
wget -q "${KNATIVE_SERVING_REPO_DOWNLOAD_URL}/knative-v${KNATIVE_SERVING_VERSION}/serving-post-install-jobs.yaml"
SERVING_IMAGE_LIST+=($(yq 'select(di == 0) | .spec.template.spec.containers | .[] | .image' ./serving-post-install-jobs.yaml))

# NOTE: not printing static list
printf "%s\n" "${EVENTING_IMAGE_LIST[@]}" | sort -u
printf "%s\n" "${SERVING_IMAGE_LIST[@]}" | sort -u
printf "%s\n" "${IMAGE_LIST[@]}" | sort -u
