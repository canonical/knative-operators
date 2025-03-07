#!/bin/bash
#
# This script returns list of container images that are managed by this charm and/or its workload
set -xe

IMAGE_LIST=()
IMAGE_LIST+=($(find . -type f -name metadata.yaml -exec yq '.resources | to_entries | .[] | .value | ."upstream-source"' {} \;))
IMAGE_LIST+=($(yq -N '.options.otel-collector-image.default' ./charms/knative-operator/config.yaml))
EVENTING_IMAGE_LIST=($(yq '.[]' ./charms/knative-eventing/src/default-custom-images.json  | sed 's/"//g'))
SERVING_IMAGE_LIST=($(yq '.[]' ./charms/knative-serving/src/default-custom-images.json  | sed 's/"//g'))

printf "%s\n" "${EVENTING_IMAGE_LIST[@]}" | sed -r '/^\s*$/d' | sort -u
printf "%s\n" "${SERVING_IMAGE_LIST[@]}" | sed -r '/^\s*$/d' | sort -u
printf "%s\n" "${IMAGE_LIST[@]}" | sed -r '/^\s*$/d' | sort -u
