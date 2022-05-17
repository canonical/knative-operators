from unittest.mock import MagicMock, call

import jinja2
import pytest

from charm_template import KubernetesManifestCharmBase
from ops.testing import Harness


@pytest.fixture
def harness():
    """Returns a harnessed charm with leader == True"""
    harness = Harness(KubernetesManifestCharmBase)
    harness.set_leader(True)
    return harness


@pytest.fixture(autouse=True)
def lightkube_client(mocker):
    """Yields a mocked lightkube client"""
    yield mocker.patch("charm_template.Client")


@pytest.fixture()
def lightkube_codecs(mocker):
    """Yields a mocked lightkube codecs"""
    yield mocker.patch("charm_template.codecs")


def test_jinja_env(harness):
    harness.begin()

    # No jinja_env set before we access it
    assert harness.charm._jinja_env is None

    # Default set and cached once we try to access it
    jinja_env = harness.charm.jinja_env
    assert isinstance(jinja_env, jinja2.Environment)
    assert harness.charm._jinja_env is jinja_env

    # Setter replaces cached value
    jinja_env_2 = jinja2.Environment()
    harness.charm.jinja_env = jinja_env_2
    assert jinja_env_2 is harness.charm.jinja_env
    assert harness.charm._jinja_env is jinja_env_2

    # Setter rejects wrong input
    with pytest.raises(ValueError):
        harness.charm.jinja_env = "not a jinja environment"


def test_render_manifests(harness, lightkube_codecs):
    harness.begin()

    mocked_jinja_env = MagicMock()
    render_return_value = "string"
    mocked_jinja_env.get_template.return_value.render.return_value = render_return_value
    harness.charm._jinja_env = mocked_jinja_env

    # Arrange state for test
    template_files = [
        "template1",
        "template2",
    ]
    harness.charm.template_files = template_files

    manifests_dir = "manifestsdir"
    harness.charm.manifests_dir = manifests_dir

    context_for_render = {
        "contextkey1": "contextvalue1",
        "contextkey2": "contextvalue2",
    }
    harness.charm.context_for_render = context_for_render

    # Act (render the templates)
    harness.charm.render_manifests()

    # Assert that the template rendering made it to jinja successfully
    # For each template, assert that we called get_template for that template and that we called
    # render with the desired context

    for i, template_file in enumerate(template_files):
        # Assert that we called get_template with this template on the ith call
        assert mocked_jinja_env.get_template.call_args_list[i] == call(template_file)
        assert mocked_jinja_env.get_template().render.call_args_list[i] == call(**context_for_render)

    # Assert load_all_yaml called as expected
    expected_string_input = "\n---\n".join([render_return_value] * len(template_files))
    lightkube_codecs.load_all_yaml.assert_called_once_with(expected_string_input)
