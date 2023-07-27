# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk
from typing import Dict

import yaml


def parse_image_config(image_config: str) -> Dict[str, str]:
    """Parses config data for a dict of images, returning the parsed value as a dict.

    This helper does not catch YAML parsing errors, leaving that up to the calling function.
    Generally, this should be called inside a `try/except YAMLError` block.
    """
    images_from_config = yaml.safe_load(image_config)

    if not images_from_config:
        images_from_config = {}

    images_from_config = remove_empty_images(images=images_from_config)

    return images_from_config


def remove_empty_images(images: Dict[str, str]):
    """Removes any image with a value of an empty string."""
    return {name: value for name, value in images.items() if value != ""}


def update_images(default_images: Dict[str, str], custom_images: Dict[str, str]) -> Dict[str, str]:
    """Returns a copy of default_images that is updated with overrides from custom_images."""
    images = default_images.copy()
    images.update(custom_images)
    return images
