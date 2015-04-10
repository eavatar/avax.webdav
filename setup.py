# -*- coding: utf-8 -*-

"""
This is a setup.py script for packaging Windows executable.

Usage:
    python setup.py build
"""


from setuptools import setup, find_packages

from avax.webdav import __version__

setup(
    name="avax.webdav",
    version=__version__,
    description="Ava WebDAV extension",
    include_package_data=True,
    zip_safe=True,
    packages=find_packages(),
    namespace_packages=['avax'],

    entry_points={
        'ava.extension': [
            'webdav = avax.webdav:WebDavExtension',
        ]
    }
)