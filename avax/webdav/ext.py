# -*- coding: utf-8 -*-
from __future__ import (absolute_import, division, unicode_literals)

import os
import logging
from ava.runtime import environ
from ava.spi.webfront import dispatcher
from avax.webdav.wsgidav.fs_dav_provider import FilesystemProvider
from avax.webdav.wsgidav.wsgidav_app import DEFAULT_CONFIG, WsgiDAVApp
from avax.webdav.archive_provider import ArchiveProvider
from avax.webdav.repo_provider import RepositoryProvider

logger = logging.getLogger(__name__)


class WebDavExtension(object):
    def __init__(self):
        logger.debug("WebDAV extension created.")

    def start(self, context):
        logger.debug('Starting WebDAV extension...')
        repository = context.get('vault')
        if not repository:
            raise RuntimeError("No vault found!")

        conf = DEFAULT_CONFIG.copy()
        conf.update({
            b"mount_path": b'/dav',
            b"provider_mapping": {},
            b"port": 5080,
            b"user_mapping": {},
            b"verbose": 1,
            b"propsmanager": False,
            b"locksmanager": True,
            b'dir_browser': {
                b"enable": False,
                b"response_trailer": b'',
                b"davmount": False,
                b"ms_mount": False,
                b"ms_sharepoint_plugin": True,
                b"ms_sharepoint_urls": False,
            },
        })

        dav_app = WsgiDAVApp(conf, repository)
        dispatcher.mount(b'/dav', dav_app)

        logger.debug("WebDAV extension started.")

    def stop(self, context):
        logger.debug('WebDAV extension stopped.')
