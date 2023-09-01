#!/bin/bash
#
# This script returns list of container images that are managed by this charm and/or its workload
#
# static list
STATIC_IMAGE_LIST=(
# manual addition based on https://github.com/canonical/knative-operators/issues/137
# TO-DO: This images are present in deployment, but either cannot be found in YAMLs and/or their SHA do not match the deployed versions
gcr.io/knative-releases/knative.dev/pkg/apiextensions/storageversion/cmd/migrate@sha256:59431cf8337532edcd9a4bcd030591866cc867f13bee875d81757c960a53668d
)
# dynamic list
IMAGE_LIST=()
IMAGE_LIST+=($(find . -type f -name metadata.yaml -exec yq '.resources | to_entries | .[] | .value | ."upstream-source"' {} \;))
IMAGE_LIST+=($(grep image charms/knative-operator/src/manifests/observability/collector.yaml.j2 | awk '{print $2}' | sort --unique))
# obtain knative eventing version and corresponding knative release information
KNATIVE_EVENTING_VERSION=$(yq -N '.options.version.default' ./charms/knative-eventing/config.yaml)
KNATIVE_EVENTING_REPO_DOWNLOAD_URL=https://github.com/knative/eventing/releases/download/
EVENTING_IMAGE_LIST=()
wget -q "${KNATIVE_EVENTING_REPO_DOWNLOAD_URL}/knative-v${KNATIVE_EVENTING_VERSION}/eventing-core.yaml"
EVENTING_IMAGE_LIST+=($(yq -N '.spec.template.spec.containers | .[] | .image' ./eventing-core.yaml))
wget -q "${KNATIVE_EVENTING_REPO_DOWNLOAD_URL}/knative-v${KNATIVE_EVENTING_VERSION}/eventing.yaml"
EVENTING_IMAGE_LIST+=($(yq -N '.spec.template.spec.containers | .[] | .image' ./eventing.yaml))
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
# obtain net istio images based on hardcoded version
NET_ISTIO_VERSION="${KNATIVE_SERVING_VERSION}"
# NOTE: for KNative Serving version 1.10.2 Net Istio version must be set to 1.11.0
#       this need to be reviewed if KNative Serving version is changed
if [ $KNATIVE_SERVING_VERSION == "1.10.2" ]; then
  NET_ISTIO_VERSION="1.11.0"
fi
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

# TO-DO not printing static list
#printf "%s\n" "${STATIC_IMAGE_LIST[@]}" | sort -u
printf "%s\n" "${EVENTING_IMAGE_LIST[@]}" | sed -r '/^\s*$/d' | sort -u
printf "%s\n" "${SERVING_IMAGE_LIST[@]}" | sed -r '/^\s*$/d' | sort -u
printf "%s\n" "${NET_ISTIO_IMAGE_LIST[@]}" | sed -r '/^\s*$/d' | sort -u
printf "%s\n" "${IMAGE_LIST[@]}" | sed -r '/^\s*$/d' | sort -u
