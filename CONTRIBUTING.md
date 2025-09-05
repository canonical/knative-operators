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


## How to Manage Python Dependencies and Environments


### Prerequisites

`tox` is the only tool required locally, as `tox` internally installs and uses `poetry`, be it to manage Python dependencies or to run `tox` environments. To install it: `pipx install tox`.

Optionally, `poerty` can be additionally installed independently just for the sake of running Python commands locally outside of `tox` during debugging/development. To install it: `pipx install poetry`.


### Updating Dependencies

To add/update/remove any dependencies and/or to upgrade Python, simply:

1. add/update/remove such dependencies to/in/from the desired group(s) below `[tool.poetry.group.<your-group>.dependencies]` in `pyproject.toml`, and/or upgrade Python itself in `requires-python` under `[project]`

    _⚠️ dependencies for the charm itself are also defined as dependencies of a dedicated group called `charm`, specifically below `[tool.poetry.group.charm.dependencies]`, and not as project dependencies below `[project.dependencies]` or `[tool.poetry.dependencies]` ⚠️_

2. run `tox -e update-requirements` to update the lock file

    by this point, `poerty`, through `tox`, will let you know if there are any dependency conflicts to solve.

3. optionally, if you also want to update your local environment for running Python commands/scripts yourself and not through tox, see [Running Python Environments](#running-python-environments) below


### Running `tox` Environments

To run `tox` environments, either locally for development or in CI workflows for testing, ensure to have `tox` installed first and then simply run your `tox` environments natively (e.g.: `tox -e lint`). `tox` will internally first install `poetry` and then rely on it to install and run its environments.


### Running Python Environments

To run Python commands locally for debugging/development from any environments built from any combinations of dependency groups without relying on `tox`:
1. ensure you have `poetry` installed
2. install any required dependency groups: `poetry install --only <your-group-a>,<your-group-b>` (or all groups, if you prefer: `poetry install --all-groups`)
3. run Python commands via poetry: `poetry run python3 <your-command>`
