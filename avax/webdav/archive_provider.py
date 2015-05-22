# -*- coding: utf-8 -*-
""" DAVProvider using avax.repository.
"""
from __future__ import (absolute_import, division, unicode_literals)

import os
import logging
from binascii import b2a_hex

from avax.repository.errors import ObjectNotExist

from .wsgidav import util
from .wsgidav.dav_error import DAVError, HTTP_FORBIDDEN
from .wsgidav.dav_provider import DAVProvider, DAVCollection, DAVNonCollection

BUFFER_SIZE = 8192

logger = logging.getLogger(__name__)
# logger.addHandler(logging.NullHandler())


class FileResource(DAVNonCollection):
    """Represents a single existing DAV resource instance.

    See also _DAVResource, DAVNonCollection, and FilesystemProvider.
    """
    def __init__(self, batch, path, environ, content_item):
        super(FileResource, self).__init__(path, environ)
        self._batch = batch
        self._content_item = content_item
        # Setting the name from the file path should fix the case on Windows
        self.name = os.path.basename(self.path)
        # self.name = self.name.encode("utf8")

    # Getter methods for standard live properties
    def getContentLength(self):
        return self._content_item.length

    def getContentType(self):
        mime_type = self._content_item.mime_type
        if not mime_type or mime_type == b'application/octet-stream':
            return util.guessMimeType(self.path)
        return mime_type

    def getCreationDate(self):
        return self._content_item.created_at

    def getDisplayName(self):
        return self.name

    def getEtag(self):
        return b2a_hex(self._content_item.psha)

    def getLastModified(self):
        return self._content_item.modified_at

    def supportEtag(self):
        return True

    def supportRanges(self):
        return True

    def getContent(self):
        """Open content as a stream for reading.

        See DAVResource.getContent()
        """
        assert not self.isCollection

        return self._content_item.get_content_as_stream()

    def beginWrite(self, contentType=None):
        """Open content as a stream for writing.

        See DAVResource.beginWrite()
        """
        assert not self.isCollection
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)
        if contentType:
            logger.debug("Client provided content type: %s", contentType)
            self._content_item.mime_type = contentType
            self._batch.dirty = True
        return self._content_item.put_content_as_stream()

    def endWrite(self, withErrors):
        if withErrors:
            logger.info("Finished uploading content with errors.")
        else:
            logger.debug("Finished uploading content.")

    def delete(self):
        """Remove this resource or collection (recursive).

        See DAVResource.delete()
        """

        util.log("Delete folder: %s" % self.name)

        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        self._batch.remove_document(self.path)
        self.removeAllProperties(True)
        self.removeAllLocks(True)

    def _handleDelete(self):
        logger.debug("Handling delete request...")
        self.delete()
        return True

    def _handleCopy(self, destPath, depthInfinity):
        logger.debug("Handing copy request...")

        self._batch.copy_item(self.path, destPath, overwrite=True)
        return True

    def _handleMove(self, destPath):
        logger.debug("Handing move request...")

        self._batch.move_item(self.path, destPath, overwrite=True)
        return True

    def copyMoveSingle(self, destPath, isMove):
        """See DAVResource.copyMoveSingle() """
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)
        # Copy file (overwrite, if exists)
        assert not util.isEqualOrChildUri(self.path, destPath)
        if isMove:
            self._batch.move_item(self.path, destPath, overwrite=True)
        else:
            self._batch.copy_item(self.path, destPath, overwrite=True)

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
        assert not util.isEqualOrChildUri(self.path, destPath)
        self._batch.move_item(self.path, destPath)
        self._batch.dirty = True

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
    def __init__(self, batch, path, environ, content_item):
        super(FolderResource, self).__init__(path, environ)
        self._batch = batch
        self._content_item = content_item
        # Setting the name from the file path should fix the case on Windows
        self.name = os.path.basename(path)


    # Getter methods for standard live properties
    def getCreationDate(self):
        return self._content_item.created_at

    def getDisplayName(self):
        return self.name

    def getDirectoryInfo(self):
        return None

    def getEtag(self):
        return b2a_hex(self._content_item.psha)

    def getLastModified(self):
        return self._content_item.modified_at

    def getMemberNames(self):
        """Return list of direct collection member names (utf-8 encoded).

        See DAVCollection.getMemberNames()
        """

        name_list = []
        for name in self._content_item.entry_names():
            name_list.append(name)
        logger.info("member names: %r", name_list)
        return name_list

    def getMember(self, name):
        """Return direct collection member (DAVResource or derived).

        See DAVCollection.getMember()
        """
        content_item = self._content_item.lookup(name)
        logger.info("getMember %s in %s ", name, content_item.name)
        path = util.joinUri(self.path, name)
        if content_item.is_folder():
            res = FolderResource(self._batch, path, self.environ, content_item)
        elif content_item.is_document():
            res = FileResource(self._batch, path, self.environ, content_item)
        else:
            logger.info("Skipping non-file %s" % path)
            res = None

        return res

    # --- Read / write ---------------------------------------------------------

    def createEmptyResource(self, name):
        """Create an empty (length-0) resource.

        See DAVResource.createEmptyResource()
        """
        # if isinstance(name, str):
        #    name = unicode(name, 'utf-8')
        assert b"/" not in name

        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        path = util.joinUri(self.path, name)
        self._content_item.create_document(name)
        self._batch.dirty = True
        return self.provider.getResourceInst(path, self.environ)

    def createCollection(self, name):
        """Create a new collection as member of self.

        See DAVResource.createCollection()
        """
        # if isinstance(name, str):
        #     name = unicode(name, 'utf-8')
        assert b"/" not in name

        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        path = util.joinUri(self.path, name)
        self._content_item.create_folder(name)
        self._batch.dirty = True

    def delete(self):
        """Remove this resource or collection (recursive).

        See DAVResource.delete()
        """
        logger.debug("Delete folder: %s", self.name)
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)
        try:
            self._batch.remove_folder(self.path, forced=True)
            logger.debug("Folder %s deleted.", self.name)
        except Exception as e:
            logger.error('Failed to delete folder.', e, exc_info=True)

        self.removeAllProperties(True)
        self.removeAllLocks(True)

    def handleDelete(self):
        logger.debug("Handling delete request...")
        self.delete()
        return True

    def handleCopy(self, destPath, depthInfinity):
        logger.debug("Handling copy request...")

        self._batch.copy_item(self.path, destPath, overwrite=True)
        self._batch.dirty = True
        return True

    def handleMove(self, destPath):
        logger.debug("Handling move request...")

        self._batch.move_item(self.path, destPath, overwrite=True)
        self._batch.dirty = True
        return True

    def copyMoveSingle(self, destPath, isMove):
        """See DAVResource.copyMoveSingle() """
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        if isMove:
            self._batch.move_item(self.path, destPath, overwrite=True)
        else:
            self._batch.copy_item(self.path, destPath, overwrite=True)

        self._batch.dirty = True

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
        """Return True, if moveRecursive() is available (see comments there).
        """
        return True

    def supportRecursiveDelete(self):
        return True

    def moveRecursive(self, destPath):
        """See DAVResource.moveRecursive() """
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)

        self._batch.move_item(self.path, destPath)
        self._batch.dirty = True

        # Move dead properties
        if self.provider.propManager:
            destRes = self.provider.getResourceInst(destPath, self.environ)
            self.provider.propManager.moveProperties(self.getRefUrl(), destRes.getRefUrl(),
                                                     withChildren=True)


class ArchiveProvider(DAVProvider):
    def __init__(self, repository, name, archive, readonly=False):
        super(ArchiveProvider, self).__init__()
        self.repository = repository
        self.name = name
        self.readonly = readonly

        # for test
        self.archive = archive
        # with self.archive.begin_batch() as batch:
        #    batch.create_folders(b"/public")

    def __repr__(self):
        return "ArchiveProvider[%s]" % self.name

    def isReadOnly(self):
        return False

    def exists(self, path, environ):
        batch = environ.get(b'batch', None)
        return batch.item_exists(path)

    def getResourceInst(self, full_path, environ):
        """Return info dictionary for path.

        See DAVProvider.getResourceInst()
        """
        self._count_getResourceInst += 1
        assert full_path is not None

        path = b'/' + full_path.strip(b'/')
        logger.debug("Archive Path: '%s'", path)

        batch = environ.get(b'batch', None)
        assert batch is not None

        try:
            content_item = batch.lookup(path)
        except ObjectNotExist:
            logger.info("No object bound to path: %s", path)
            return None

        if content_item.is_folder():
            return FolderResource(batch, path, environ, content_item)

        return FileResource(batch, path, environ, content_item)
