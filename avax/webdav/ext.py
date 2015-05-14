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
        self.user_folder_path = os.path.join(environ.pod_dir(), 'temp')
        # self.user_folder_path = '/tmp'

    def start(self, context):
        logger.debug('Starting WebDAV extension...')
        user_folder = FilesystemProvider(self.user_folder_path)
        repository = context.get('repository')
        if not repository:
            raise RuntimeError("No repository found!")

        repo_provider = RepositoryProvider(repository)
        files_provider = ArchiveProvider(repository, b'files')

        conf = DEFAULT_CONFIG.copy()
        conf.update({
            b"mount_path": b'/dav',
            b"provider_mapping": {b'/': repo_provider,
                                  b'/files': files_provider,
                                  b"/temp": user_folder, },
            b"port": 5080,
            b"user_mapping": {},
            b"verbose": 2,
            b"propsmanager": True,
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
