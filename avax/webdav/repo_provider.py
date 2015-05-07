# -*- coding: utf-8 -*-
""" DAVProvider using avax.repository.
"""
from __future__ import (absolute_import, division)

import os
import logging

from avax.repository.errors import ObjectNotExist

from .wsgidav import util
from .wsgidav.dav_error import DAVError, HTTP_FORBIDDEN
from .wsgidav.dav_provider import DAVProvider, DAVCollection, DAVNonCollection

BUFFER_SIZE = 8192

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class FileResource(DAVNonCollection):
    """Represents a single existing DAV resource instance.

    See also _DAVResource, DAVNonCollection, and FilesystemProvider.
    """
    def __init__(self, batch, path, environ, fileobj):
        super(FileResource, self).__init__(path, environ)
        self._batch = batch
        self._fileobj = fileobj
        # Setting the name from the file path should fix the case on Windows
        self.name = os.path.basename(self.path)
        self.name = self.name.encode("utf8")

    # Getter methods for standard live properties
    def getContentLength(self):
        return self._fileobj.length

    def getContentType(self):
        return self._fileobj.mime_type

    def getCreationDate(self):
        return self._fileobj.created_at

    def getDisplayName(self):
        return self.name

    def getEtag(self):
        return self._fileobj.hexsha

    def getLastModified(self):
        return self._fileobj.modified_at

    def supportEtag(self):
        return True

    def supportRanges(self):
        return True

    def getContent(self):
        """Open content as a stream for reading.

        See DAVResource.getContent()
        """
        assert not self.isCollection

        return self._fileobj.get_content_as_stream()

    def beginWrite(self, contentType=None):
        """Open content as a stream for writing.

        See DAVResource.beginWrite()
        """
        assert not self.isCollection
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        return self._fileobj.put_content_as_stream()

    def endWrite(self, withErrors=True):
        logger.debug("endWrite invoked, try to commit.")
        if not self._batch.readonly:
            self._batch.commit()

    def delete(self):
        """Remove this resource or collection (recursive).

        See DAVResource.delete()
        """
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        self._batch.remove_document(self.path)
        self._batch.commit()
        self.removeAllProperties(True)
        self.removeAllLocks(True)

    def copyMoveSingle(self, destPath, isMove):
        """See DAVResource.copyMoveSingle() """
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)
        # Copy file (overwrite, if exists)

        if isMove:
            self._batch.move_file(self.path, destPath)
        else:
            self._batch.copy_file(self.path, destPath)

        # (Live properties are copied by copy2 or copystat)
        # Copy dead properties
        propMan = self.provider.propManager
        if propMan:
            destRes = self.provider.getResourceInst(destPath, self.environ)
            if isMove:
                propMan.moveProperties(self.getRefUrl(), destRes.getRefUrl(),
                                       withChildren=False)
            else:
                propMan.copyProperties(self.getRefUrl(), destRes.getRefUrl())

    def supportRecursiveMove(self, destPath):
        """Return True, if moveRecursive() is available (see comments there)."""
        return True

    def moveRecursive(self, destPath):
        """See DAVResource.moveRecursive() """
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        logger.debug("moveRecursive(%s, %s)" % (self.path, destPath))
        self._batch.move_file(self.path, destPath)

        # (Live properties are copied by copy2 or copystat)
        # Move dead properties
        if self.provider.propManager:
            destRes = self.provider.getResourceInst(destPath, self.environ)
            self.provider.propManager.moveProperties(self.getRefUrl(), destRes.getRefUrl(),
                                                     withChildren=True)


class FolderResource(DAVCollection):
    """Represents a single existing file system folder DAV resource.

    See also _DAVResource, DAVCollection, and FilesystemProvider.
    """
    def __init__(self, batch, path, environ, fileobj):
        super(FolderResource, self).__init__(path, environ)
        self._batch = batch
        self._fileobj = fileobj
        # Setting the name from the file path should fix the case on Windows
        self.name = os.path.basename(path)
        self.name = self.name.encode("utf8")


    # Getter methods for standard live properties
    def getCreationDate(self):
        return self._fileobj.created_at

    def getDisplayName(self):
        return self.name

    def getDirectoryInfo(self):
        return None

    def getEtag(self):
        return self._fileobj.hexsha

    def getLastModified(self):
        return self._fileobj.modified_at

    def getMemberNames(self):
        """Return list of direct collection member names (utf-8 encoded).

        See DAVCollection.getMemberNames()
        """

        name_list = []
        for name in self._fileobj.entry_names():
            name_list.append(name)
        return name_list

    def getMember(self, name):
        """Return direct collection member (DAVResource or derived).

        See DAVCollection.getMember()
        """
        fileobj = self._fileobj.lookup(name)
        fp = os.path.join(self.path, name.decode("utf8"))
#        name = name.encode("utf8")
        path = util.joinUri(self.path, name)
        if fileobj.is_folder():
            res = FolderResource(self._batch, path, self.environ, fileobj)
        elif fileobj.is_document():
            res = FileResource(self._batch, path, self.environ, fileobj)
        else:
            logger.debug("Skipping non-file %s" % fp)
            res = None

        return res

    # --- Read / write ---------------------------------------------------------

    def createEmptyResource(self, name):
        """Create an empty (length-0) resource.

        See DAVResource.createEmptyResource()
        """
        if isinstance(name, str):
            name = unicode(name, 'utf-8')
        assert "/" not in name

        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        path = util.joinUri(self.path, name)
        self._fileobj.create_document(name)
        self._batch.commit()
        return self.provider.getResourceInst(path, self.environ)

    def createCollection(self, name):
        """Create a new collection as member of self.

        See DAVResource.createCollection()
        """
        if isinstance(name, str):
            name = unicode(name, 'utf-8')
        assert "/" not in name

        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        path = util.joinUri(self.path, name)
        self._fileobj.create_folder(name)
        self._batch.commit()

    def delete(self):
        """Remove this resource or collection (recursive).

        See DAVResource.delete()
        """
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        self._batch.remove_folder(self.path)

        self.removeAllProperties(True)
        self.removeAllLocks(True)

        self._batch.commit()

    def copyMoveSingle(self, destPath, isMove):
        """See DAVResource.copyMoveSingle() """
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        if isMove:
            self._batch.move_file(self.path, destPath)
        else:
            self._batch.copy_files(self.path, destPath)

        # Copy dead properties
        propMan = self.provider.propManager
        if propMan:
            destRes = self.provider.getResourceInst(destPath, self.environ)
            if isMove:
                propMan.moveProperties(self.getRefUrl(), destRes.getRefUrl(),
                                       withChildren=False)
            else:
                propMan.copyProperties(self.getRefUrl(), destRes.getRefUrl())

        self._batch.commit()

    def supportRecursiveMove(self, destPath):
        """Return True, if moveRecursive() is available (see comments there).
        """
        return True

    def moveRecursive(self, destPath):
        """See DAVResource.moveRecursive() """
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        self._batch.move_file(self.path, destPath)

        # (Live properties are copied by copy2 or copystat)
        # Move dead properties
        if self.provider.propManager:
            destRes = self.provider.getResourceInst(destPath, self.environ)
            self.provider.propManager.moveProperties(self.getRefUrl(), destRes.getRefUrl(),
                                                     withChildren=True)
        self._batch.commit()


class RepositoryProvider(DAVProvider):
    def __init__(self, repository, readonly=False):
        super(RepositoryProvider, self).__init__()
        self.repository = repository
        self.readonly = readonly

        # for test
        self.archive = self.repository.get_archive('files', create=False)
        with self.archive.begin_batch() as batch:
            batch.create_folders("/public")

    def _split_path(self, path):
        path = path.strip('/')

        if '/' in path:
            archive_name, rest = path.split('/', 1)
        else:
            archive_name = path
            rest = '/'

        return archive_name, rest

    def isReadOnly(self):
        return False

    def exists(self, path, environ):
        with self.archive.begin_batch(readonly=True) as batch:
            return batch.file_exists(path)

    def getResourceInst(self, full_path, environ):
        """Return info dictionary for path.

        See DAVProvider.getResourceInst()
        """
        self._count_getResourceInst += 1
        #archive_name, path = self._split_path(full_path)
        archive_name = 'files'
        if isinstance(full_path, str):
            full_path = unicode(full_path, 'utf-8')
        path = '/' + full_path.strip('/')
        logger.debug("Archive name: %s", archive_name)
        logger.debug("Path: %s", path)

        #try:
        #    archive = self.repository.get_archive(archive_name, create=False)
        #except ObjectNotExist:
        #    logger.info("Archive not exist: %s", archive_name)
        #    return None

        batch = self.archive.begin_batch()

        try:
            fileobj = batch.lookup(path)
        except ObjectNotExist:
            logger.debug("No object bound to path: %s", path)
            return None

        if fileobj.is_folder():
            return FolderResource(batch, path, environ, fileobj)

        return FileResource(batch, path, environ, fileobj)
