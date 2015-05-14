# -*- coding: utf-8 -*-
from __future__ import (absolute_import, division, unicode_literals)

import io
import logging

from .wsgidav import util
from .wsgidav.dav_error import DAVError, HTTP_FORBIDDEN
from .wsgidav.dav_provider import DAVProvider, DAVCollection, DAVNonCollection

logger = logging.getLogger(__name__)


class ArchiveResource(DAVCollection):

    def __init__(self, path, environ, archive_name):
        super(ArchiveResource, self).__init__(path, environ)
        self.name = archive_name

    def getDisplayName(self):
        return self.name

    def getEtag(self):
        return self.name

    def supportEtag(self):
        return True

    def delete(self):
        """Remove this resource or collection (recursive).

        See DAVResource.delete()
        """
        logger.debug("Delete archive: %s", self.name)


class RepositoryRoot(DAVCollection):
    def __init__(self, path, environ, repository):
        super(RepositoryRoot, self).__init__(path, environ)
        self._repository = repository

        self.name = b'Repository'

    # Getter methods for standard live properties
    def getCreationDate(self):
        return self._repository.created_at

    def getDisplayName(self):
        return self.name

    def getDirectoryInfo(self):
        return None

    def getEtag(self):
        return self._repository.hexsha

    def getLastModified(self):
        return self._repository.modified_at

    def getMemberNames(self):
        """Return list of direct collection member names (utf-8 encoded).

        See DAVCollection.getMemberNames()
        """

        name_list = []
        for name in self._repository.archive_names():
            name_list.append(name)
        return name_list

    def getMember(self, name):
        """Return direct collection member (DAVResource or derived).

        See DAVCollection.getMember()
        """
        item = self._repository.find(name)
        return ArchiveResource(b'/' + name, self.environ, name)

    def createCollection(self, name):
        """Create a new collection as member of self.

        See DAVResource.createCollection()
        """
        self._repository.create_archive(name)

    def delete(self):
        """Remove this resource or collection (recursive).

        See DAVResource.delete()
        """
        raise DAVError(HTTP_FORBIDDEN)


class RepositoryProvider(DAVProvider):

    def __init__(self, repository):
        super(RepositoryProvider, self).__init__()
        self.repository = repository

    def _split_path(self, path):
        path = path.strip(b'/')

        if b'/' in path:
            archive_name, rest = path.split(b'/', 1)
        else:
            archive_name = path
            rest = b'/'

        return archive_name, rest

    def isReadOnly(self):
        return False

    def exists(self, path, environ):
        path = path.strip(b'/')
        return self.repository.has_archive(path)

    def getResourceInst(self, path, environ):
        """Return info dictionary for path.

        See DAVProvider.getResourceInst()
        """
        self._count_getResourceInst += 1

        return RepositoryRoot(path, environ, self.repository)

