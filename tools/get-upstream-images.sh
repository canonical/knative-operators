#!/bin/bash
#
# This script returns list of container images that are managed by this charm and/or its workload
set -xe

IMAGE_LIST=()
IMAGE_LIST+=($(find . -type f -name metadata.yaml -exec yq '.resources | to_entries | .[] | .value | ."upstream-source"' {} \;))
IMAGE_LIST+=($(yq -N '.options.otel-collector-image.default' ./charms/knative-operator/config.yaml))
# obtain knative eventing version and corresponding knative release information
KNATIVE_EVENTING_VERSION=$(yq -N '.options.version.default' ./charms/knative-eventing/config.yaml)
KNATIVE_EVENTING_REPO_DOWNLOAD_URL=https://github.com/knative/eventing/releases/download/
EVENTING_IMAGE_LIST=()
wget -q "${KNATIVE_EVENTING_REPO_DOWNLOAD_URL}/knative-v${KNATIVE_EVENTING_VERSION}/eventing-core.yaml"
EVENTING_IMAGE_LIST+=($(yq -N '.spec.template.spec.containers | .[] | .image' ./eventing-core.yaml))
wget -q "${KNATIVE_EVENTING_REPO_DOWNLOAD_URL}/knative-v${KNATIVE_EVENTING_VERSION}/eventing.yaml"
EVENTING_IMAGE_LIST+=($(yq -N '.spec.template.spec.containers | .[] | .image' ./eventing.yaml))
wget -q "${KNATIVE_EVENTING_REPO_DOWNLOAD_URL}/knative-v${KNATIVE_EVENTING_VERSION}/eventing-post-install.yaml"
EVENTING_IMAGE_LIST+=($(yq -N '.spec.template.spec.containers | .[] | .image' ./eventing-post-install.yaml))
# obtain knative serving version and corresponding knative release information
KNATIVE_SERVING_VERSION=$(yq -N '.options.version.default' ./charms/knative-serving/config.yaml)
KNATIVE_SERVING_REPO_DOWNLOAD_URL=https://github.com/knative/serving/releases/download/
SERVING_IMAGE_LIST=()
wget -q "${KNATIVE_SERVING_REPO_DOWNLOAD_URL}/knative-v${KNATIVE_SERVING_VERSION}/serving-core.yaml"
SERVING_IMAGE_LIST+=($(yq -N '.spec.image' ./serving-core.yaml))
SERVING_IMAGE_LIST+=($(yq -N '.data.queue-sidecar-image' ./serving-core.yaml))
SERVING_IMAGE_LIST+=($(yq -N '.spec.template.spec.containers | .[] | .image' ./serving-core.yaml))
wget -q "${KNATIVE_SERVING_REPO_DOWNLOAD_URL}/knative-v${KNATIVE_SERVING_VERSION}/serving-hpa.yaml"
SERVING_IMAGE_LIST+=($(yq -N '.spec.template.spec.containers | .[] | .image' ./serving-hpa.yaml))
wget -q "${KNATIVE_SERVING_REPO_DOWNLOAD_URL}/knative-v${KNATIVE_SERVING_VERSION}/serving-default-domain.yaml"
SERVING_IMAGE_LIST+=($(yq -N '.spec.template.spec.containers | .[] | .image' ./serving-default-domain.yaml))
wget -q "${KNATIVE_SERVING_REPO_DOWNLOAD_URL}/knative-v${KNATIVE_SERVING_VERSION}/serving-storage-version-migration.yaml"
SERVING_IMAGE_LIST+=($(yq -N '.spec.template.spec.containers | .[] | .image' ./serving-storage-version-migration.yaml))
wget -q "${KNATIVE_SERVING_REPO_DOWNLOAD_URL}/knative-v${KNATIVE_SERVING_VERSION}/serving-post-install-jobs.yaml"
SERVING_IMAGE_LIST+=($(yq -N '.spec.template.spec.containers | .[] | .image' ./serving-post-install-jobs.yaml))

# For Serving 1.16.0 (CKF 1.10) we have to use 1.16.0 for net-istio
# https://github.com/kubeflow/manifests/blob/v1.10.0-rc.0/common/knative/README.md?plain=1#L8
NET_ISTIO_VERSION="1.16.0"
NET_ISTIO_REPO_DOWNLOAD_URL=https://github.com/knative-extensions/net-istio/releases/download/
NET_ISTIO_IMAGE_LIST=()
wget -q "${NET_ISTIO_REPO_DOWNLOAD_URL}knative-v${NET_ISTIO_VERSION}/net-istio.yaml"
NET_ISTIO_IMAGE_LIST+=($(yq -N '.spec.template.spec.containers | .[] | .image' ./net-istio.yaml))

# remove nulls from arrays
del_null="null"
EVENTING_IMAGE_LIST=("${EVENTING_IMAGE_LIST[@]/$del_null}")
SERVING_IMAGE_LIST=("${SERVING_IMAGE_LIST[@]/$del_null}")
NET_ISTIO_IMAGE_LIST=("${NET_ISTIO_IMAGE_LIST[@]/$del_null}")
IMAGE_LIST=("${IMAGE_LIST[@]/$del_null}")

printf "%s\n" "${EVENTING_IMAGE_LIST[@]}" | sed -r '/^\s*$/d' | sort -u
printf "%s\n" "${SERVING_IMAGE_LIST[@]}" | sed -r '/^\s*$/d' | sort -u
printf "%s\n" "${NET_ISTIO_IMAGE_LIST[@]}" | sed -r '/^\s*$/d' | sort -u
printf "%s\n" "${IMAGE_LIST[@]}" | sed -r '/^\s*$/d' | sort -u

rm eventing-core.yaml eventing-post-install.yaml eventing.yaml net-istio.yaml \
  serving-core.yaml serving-default-domain.yaml serving-hpa.yaml \
  serving-post-install-jobs.yaml serving-storage-version-migration.yaml
