#!/bin/bash
#
# This script returns list of container images that are managed by this charm and/or its workload
#
# dynamic list
IMAGE_LIST=()
IMAGE_LIST+=($(grep image charms/knative-operator/src/manifests/observability/collector.yaml.j2 | awk '{print $2}' | sort --unique))
printf "%s\n" "${IMAGE_LIST[@]}"

