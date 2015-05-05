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
    description="The WebDAV extension for Ava platform.",
    include_package_data=True,
    zip_safe=True,
    packages=find_packages(exclude=['tests']),
    namespace_packages=['avax'],

    entry_points={
        'ava.extension': [
            '90_webdav = avax.webdav.ext:WebDavExtension',
        ]
    },

    classifiers=["Development Status :: 4 - Beta",
                 "Intended Audience :: Information Technology",
                 "Intended Audience :: Developers",
                 "Intended Audience :: System Administrators",
                 "License :: OSI Approved :: MIT License",
                 "Operating System :: OS Independent",
                 "Programming Language :: Python",
                 "Topic :: Internet :: WWW/HTTP",
                 "Topic :: Internet :: WWW/HTTP :: HTTP Servers",
                 "Topic :: Internet :: WWW/HTTP :: Dynamic Content",
                 "Topic :: Internet :: WWW/HTTP :: WSGI",
                 "Topic :: Internet :: WWW/HTTP :: WSGI :: Application",
                 "Topic :: Internet :: WWW/HTTP :: WSGI :: Server",
                 "Topic :: Software Development :: Libraries :: Python Modules",
                 ],
    keywords = "web wsgi webdav application server",
    license = "The MIT License",

)