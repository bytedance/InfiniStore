# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information


import sys
import os
from unittest.mock import MagicMock


sys.path.insert(0, os.path.abspath("../.."))

project = "infinistore"
copyright = "2025, deanraccoon@gmail.com"
author = "deanraccoon@gmail.com"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
]

mock_torch = MagicMock(name="torch")
mock_tensor = MagicMock(name="torch.Tensor")
mock__infinistore = MagicMock(name="infinistore._infinistore")

sys.modules["torch"] = mock_torch
sys.modules["torch.Tensor"] = mock_tensor
sys.modules["infinistore._infinistore"] = mock__infinistore


templates_path = ["_templates"]
exclude_patterns = []

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "alabaster"
html_static_path = ["_static"]
