# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk
from typing import Dict

import yaml


def parse_image_config(image_config: str) -> Dict[str, str]:
    """Parses config data for a dict of images, returning the parsed value as a dict."""
    try:
        images_from_config = yaml.safe_load(image_config)
    except yaml.YAMLError as err:
        raise ValueError(
            f"Encountered error while parsing image config with value '{image_config}'"
        ) from err

    if not images_from_config:
        images_from_config = {}

    # Remove empty images
    images_from_config = {name: value for name, value in images_from_config.items() if value != ""}

    return images_from_config


def update_images(default_images: Dict[str, str], custom_images: Dict[str, str]) -> Dict[str, str]:
    """Updates a default set of images with a custom_image dict."""
    images = default_images.copy()
    images.update(custom_images)
    return images
