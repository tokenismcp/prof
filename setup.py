"""setuptools shim for old pip (<21.3) editable installs.

Modern pip reads pyproject.toml directly; this file only exists so
`pip install -e .` also works on older toolchains (e.g. Xcode Python).
Metadata lives in setup.cfg.
"""

from setuptools import setup

setup()
