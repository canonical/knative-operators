# Update instructions
To update the images of the knative operators, you should:
1. Update the operator and webhook image in the metadata.yaml of `knative-operator` charm with the new version.
2. Update the otel collector image in the config.yaml of `knative-operator` charm with the new version.
3. Update the upstream image gathering script `tools/get-upstream-images.sh` for the new version, explained in detail below.
4. Run the updated upstream image gathering script `tools/get-upstream-images.sh` to get the new images for serving and eventing.
5. Update the `default-custom-images.json` files in `knative-serving` and `knative-eventing` charm directories under `src/` with the new images.

## Update upstream image gathering script

For every release, we'll need to update the image gather scripts for fetching the images used by Knative Charms.

To get an overview of how the script works please read https://github.com/canonical/knative-operators/issues/142

The script also needs to gather images for `net-istio`, that has it's own release cadance (although almost 1-1 with Knative Serving, but sometimes tags for Serving might not exist for `net-istio`).

**Process:**
1. Confirm the Knative Serving version
2. Deduce the `net-istio` that should be used
  * If you update based on a Kubeflow release, then you can deduce this from [upstream Kubeflow manifests](https://github.com/kubeflow/manifests/blob/v1.9-branch/common/knative/README.md?plain=1#L8) (make sure to checkout to correct release branch). Note that in the Kubeflow's README this will be referred as `Knative ingress controller for Istio`
  * If you update to an arbitrary Knative Serving version, then check the branches of [`net-istio`](https://github.com/knative-extensions/net-istio/tags) and pick the closest one to your Knative Serving release
3. Update the `tools/get-upstream-images.sh` script to use the selected version of `net-istio`
  * If the `net-istio` tag is not 1-1 with the Serving version then hardcode the version of `net-istio` in the script
