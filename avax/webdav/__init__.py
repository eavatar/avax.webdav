# -*- coding: utf-8 -*-
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)

import logging

logger = logging.getLogger(__name__)

__version__ = '0.1.0'


class WebDavExtension(object):
    def __init__(self):
        logger.debug("WebDAV extension created.")

    def start(self, context):
        logger.debug('WebDAV extension started.')

    def stop(self, context):
        logger.debug('WebDAV extension stopped.')
