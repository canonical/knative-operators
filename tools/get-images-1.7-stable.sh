#!/bin/bash
#
# This script returns list of container images that are managed by this charm and/or its workload
#
# static list
STATIC_IMAGE_LIST=(
)
# dynamic list
git checkout origin/track/1.8
IMAGE_LIST=()
IMAGE_LIST+=($(grep image charms/knative-operator/src/manifests/observability/collector.yaml.j2 | awk '{print $2}'))

printf "%s\n" "${STATIC_IMAGE_LIST[@]}"
printf "%s\n" "${IMAGE_LIST[@]}"
