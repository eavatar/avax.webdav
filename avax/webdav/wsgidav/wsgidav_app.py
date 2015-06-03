# -*- coding: utf-8 -*-
"""
WSGI container, that handles the HTTP requests. This object is passed to the 
WSGI server and represents our WsgiDAV application to the outside. 

On init:

    Use the configuration dictionary to initialize lock manager, property manager,
    domain controller. 

    Create a dictionary of share-to-provider mappings.         

    Initialize middleware objects and RequestResolver and setup the WSGI 
    application stack.
      
For every request:

    Find the registered DAV provider for the current request.   
    
    Add or modify info in the WSGI ``environ``:
    
        environ["SCRIPT_NAME"]
            Mount-point of the current share.            
        environ["PATH_INFO"]
            Resource path, relative to the mount path.
        environ["wsgidav.provider"]
            DAVProvider object that is registered for handling the current 
            request. 
        environ["wsgidav.config"]
            Configuration dictionary.
        environ["wsgidav.verbose"]
            Debug level [0-3].

    Log the HTTP request, then pass the request to the first middleware.

    Note: The OPTIONS method for the '*' path is handled directly.

See `Developers info`_ for more information about the WsgiDAV architecture.

.. _`Developers info`: http://wsgidav.readthedocs.org/en/latest/develop.html  
"""
from __future__ import absolute_import, print_function, unicode_literals

import os
import time
import sys
import threading
import urllib
import logging

from ava.runtime import environ

from ..wsgidav.dir_browser import WsgiDavDirBrowser
from ..wsgidav.dav_provider import DAVProvider
from ..wsgidav.lock_storage import LockStorageDict
from ..repo_provider import RepositoryProvider
from ..archive_provider import ArchiveProvider

from . import util
from .error_printer import ErrorPrinter
from .debug_filter import WsgiDavDebugFilter
from .http_authenticator import HTTPAuthenticator
from .request_resolver import RequestResolver
from .domain_controller import WsgiDAVDomainController
from .property_manager import PropertyManager
from .lock_manager import LockManager
from .fs_dav_provider import FilesystemProvider

__docformat__ = "reStructuredText"

READONLY_METHODS = ['GET', 'HEAD', 'OPTIONS', 'PROPFIND', 'PROPGET', ]

logger = logging.getLogger(__name__)


# Use these settings, if config file does not define them (or is totally missing)
DEFAULT_CONFIG = {
    b"mount_path": None,  # Application root, e.g. <mount_path>/<share_name>/<res_path>
    b"provider_mapping": {},
    b"host": b"localhost",
    b"port": 5080,
    b"ext_servers": [
        b"cherrypy-bundled",
        b"wsgidav",
        ],

    b"add_header_MS_Author_Via": True,

    b"propsmanager": None,  # True: use property_manager.PropertyManager
    b"locksmanager": True,  # True: use lock_manager.LockManager
    
    # HTTP Authentication Options
    b"user_mapping": {},       # dictionary of dictionaries
    b"domaincontroller": None, # None: domain_controller.WsgiDAVDomainController(user_mapping)
    b"acceptbasic": True,      # Allow basic authentication, True or False
    b"acceptdigest": True,     # Allow digest authentication, True or False
    b"defaultdigest": True,    # True (default digest) or False (default basic)
    
    b"enable_loggers": [
                      ],

    # Verbose Output
    b"verbose": 1,        # 0 - no output (excepting application exceptions)
                         # 1 - show single line request summaries (for HTTP logging)
                         # 2 - show additional events
                         # 3 - show full request/response header info (HTTP Logging)
                         #     request body and GET response bodies not shown
    
    b"dir_browser": {
        b"enable": True,               # Render HTML listing for GET requests on collections
        b"response_trailer": b"",       # Raw HTML code, appended as footer
        b"davmount": False,            # Send <dm:mount> response if request URL contains '?davmount'
        b"ms_mount": False,            # Add an 'open as webfolder' link (requires Windows)
        b"ms_sharepoint_plugin": True, # Invoke MS Offce documents for editing using WebDAV
        b"ms_sharepoint_urls": False,  # Prepend 'ms-word:ofe|u|' to URL for MS Offce documents
    },
}


def _checkConfig(config):
    mandatoryFields = [b"provider_mapping", ]

    for field in mandatoryFields:
        if field not in config:
            raise ValueError(
                "Invalid configuration: missing required field '%s'" % field)


class WsgiDAVApp(object):

    def __init__(self, config, repository=None):

        util.initLogging(config[b"verbose"], config.get(b"enable_loggers", []))
        util.log("Default encoding: %s (file system: %s)" % (sys.getdefaultencoding(), sys.getfilesystemencoding()))

        self.config = config
        self.repository = repository
        self.repo_provider = RepositoryProvider(repository)

        # Evaluate configuration and set defaults
        _checkConfig(config)
#        response_trailer = config.get("response_trailer", "")
        self._verbose = config.get(b"verbose", 2)

        lockStorage = config.get(b"locksmanager")
        if lockStorage is True:
            lockStorage = LockStorageDict()
            
        if not lockStorage:
            self.locksManager = None
        else:
            self.locksManager = LockManager(lockStorage)

        self.propsManager = config.get(b"propsmanager")
        if not self.propsManager:
            # Normalize False, 0 to None
            self.propsManager = None
        elif self.propsManager is True:
            self.propsManager = PropertyManager()

        self.mount_path = config.get(b"mount_path")
         
        user_mapping = self.config.get(b"user_mapping", {})
        domainController = config.get(b"domaincontroller") or WsgiDAVDomainController(user_mapping)
        isDefaultDC = isinstance(domainController, WsgiDAVDomainController)

        # authentication fields
        authacceptbasic = config.get(b"acceptbasic", True)
        authacceptdigest = config.get(b"acceptdigest", True)
        authdefaultdigest = config.get(b"defaultdigest", True)
        
        # Check configuration for NTDomainController
        # We don't use 'isinstance', because include would fail on non-windows boxes.
        wdcName = b"NTDomainController"
        if domainController.__class__.__name__ == wdcName:
            if authacceptdigest or authdefaultdigest or not authacceptbasic:
                util.warn("WARNING: %s requires basic authentication.\n\tSet acceptbasic=True, acceptdigest=False, defaultdigest=False" % wdcName)
                
        # Instantiate DAV resource provider objects for every share
        self.repo_provider.setSharePath(b'/')
        self.repo_provider.setLockManager(self.locksManager)
        self.repo_provider.setPropManager(self.propsManager)

        if self.mount_path:
            self.repo_provider.setMountPath(self.mount_path)

        fs_provider = FilesystemProvider(os.path.join(environ.pod_dir(), b'temp'))
        fs_provider.setSharePath(b'/temp')
        fs_provider.setLockManager(self.locksManager)
        fs_provider.setPropManager(self.propsManager)
        if self.mount_path:
            fs_provider.setMountPath(self.mount_path)

        self.providerMap = {}
        self.providerMap[b'/'] = self.repo_provider
        self.providerMap[b'/temp'] = fs_provider

        for name in self.repository.repository_names():
            archive = self.repository.get_repository(name)
            provider = ArchiveProvider(self.repository,
                                       name,
                                       archive)
            sharePath = b'/' + name
            provider.setSharePath(sharePath)

            if self.mount_path:
                provider.setMountPath(self.mount_path)

            provider.setLockManager(self.locksManager)
            provider.setPropManager(self.propsManager)
            self.providerMap[sharePath] = provider

        if self._verbose >= 2:
            logger.debug("Using lock manager: %r", self.locksManager)
            logger.debug("Using property manager: %r", self.propsManager)
            logger.debug("Using domain controller: %s", domainController)
            logger.debug("Registered DAV providers:")

            for share, provider in self.providerMap.items():
                hint = b""
                if isDefaultDC and not user_mapping.get(share):
                    hint = b" (anonymous)"
                print("  Share '%s': %s%s" % (share, provider, hint))

        # If the default DC is used, emit a warning for anonymous realms
        if isDefaultDC and self._verbose >= 1:
            for share in self.providerMap:
                if not user_mapping.get(share):
                    # TODO: we should only warn here, if --no-auth is not given
                    logger.warning("WARNING: share '%s' will allow anonymous access.", share)

        # Define WSGI application stack
        application = RequestResolver()
        
        if config.get(b"dir_browser") and config[b"dir_browser"].get(b"enable", True):
            application = config[b"dir_browser"].get(b"app_class", WsgiDavDirBrowser)(application)

        application = HTTPAuthenticator(application, 
                                        domainController, 
                                        authacceptbasic, 
                                        authacceptdigest, 
                                        authdefaultdigest)      
        application = ErrorPrinter(application, catchall=False)

        application = WsgiDavDebugFilter(application, config)
        
        self._application = application

    def __call__(self, environ, start_response):

#        util.log("SCRIPT_NAME='%s', PATH_INFO='%s'" % (environ.get("SCRIPT_NAME"), environ.get("PATH_INFO")))
        
        # We unquote PATH_INFO here, although this should already be done by
        # the server.
        # path = urllib.unquote(environ[b"PATH_INFO"])
        path = environ[b"PATH_INFO"]

        # issue 22: Pylons sends root as u'/' 
        if isinstance(path, unicode):
            util.log("Got unicode PATH_INFO: %r" % path)
            path = path.encode("utf8")

        # Always adding these values to environ:
        environ[b"wsgidav.config"] = self.config
        environ[b"wsgidav.provider"] = None
        environ[b"wsgidav.verbose"] = self._verbose

        ## Find DAV provider that matches the share

        # sorting share list by reverse length
        #shareList = self.providerMap.keys()
        #shareList.sort(key=len, reverse=True)

        share = None 
        #for r in shareList:
        #    # @@: Case sensitivity should be an option of some sort here;
        #    #     os.path.normpath might give the preferred case for a filename.
        #    if r == b"/":
        #        share = r
        #        break
        #    elif path.upper() == r.upper() or path.upper().startswith(r.upper() + b"/"):
        #        share = r
        #        break
        strip_path = path.strip(b'/')

        if b'/' in strip_path:
            archive_name, _ = strip_path.split(b'/', 1)
        else:
            archive_name = strip_path.strip()

        share = b'/' + archive_name
        if archive_name == b'':
            provider = self.repo_provider
        else:
            provider = self.providerMap.get(share)

        logger.info("Provider:'%r' is used.", provider)

        # bind a new batch to this request.
        if isinstance(provider, ArchiveProvider):
            method = environ[b"REQUEST_METHOD"]
            logger.debug("method: %s", method)
            readonly = method in READONLY_METHODS
            if readonly:
                logger.debug("Readonly request: %s", method)
            batch = provider.archive.begin_batch(readonly=readonly)
            environ[b'batch'] = batch

        # Note: we call the next app, even if provider is None, because OPTIONS 
        #       must still be handled.
        #       All other requests will result in '404 Not Found'  
        environ[b"wsgidav.provider"] = provider

        # TODO: test with multi-level realms: 'aa/bb'
        # TODO: test security: url contains '..'
        
        # Transform SCRIPT_NAME and PATH_INFO
        # (Since path and share are unquoted, this also fixes quoted values.)
        if share == b"/" or not share:
            environ[b"PATH_INFO"] = path
        else:
            environ[b"SCRIPT_NAME"] += share
            environ[b"PATH_INFO"] = path[len(share):]
#        util.log("--> SCRIPT_NAME='%s', PATH_INFO='%s'" % (environ.get("SCRIPT_NAME"), environ.get("PATH_INFO")))

        assert isinstance(path, str)
        # See http://mail.python.org/pipermail/web-sig/2007-January/002475.html
        # for some clarification about SCRIPT_NAME/PATH_INFO format
        # SCRIPT_NAME starts with '/' or is empty
        assert environ[b"SCRIPT_NAME"] == b"" or environ[b"SCRIPT_NAME"].startswith(b"/")
        # SCRIPT_NAME must not have a trailing '/'
        assert environ[b"SCRIPT_NAME"] in (b"", b"/") or not environ[b"SCRIPT_NAME"].endswith(b"/")
        # PATH_INFO starts with '/'
        assert environ[b"PATH_INFO"] == b"" or environ[b"PATH_INFO"].startswith(b"/")

        start_time = time.time()

        def _start_response_wrapper(status, response_headers, exc_info=None):
            # util.log("_start_response_wrapped entered.")
            # Postprocess response headers
            headerDict = {}
            for header, value in response_headers:
                if header.lower() in headerDict:
                    util.warn("Duplicate header in response: %s" % header)
                headerDict[header.lower()] = value

            # Check if we should close the connection after this request.
            # http://www.w3.org/Protocols/rfc2616/rfc2616-sec4.html#sec4.4
            forceCloseConnection = False
            currentContentLength = headerDict.get(b"content-length")
            statusCode = int(status.split(b" ", 1)[0])
            contentLengthRequired = (environ[b"REQUEST_METHOD"] != b"HEAD"
                                     and statusCode >= 200
                                     and statusCode not in (204, 304))
#            print environ["REQUEST_METHOD"], statusCode, contentLengthRequired
            if contentLengthRequired and currentContentLength in (None, b""):
                # A typical case: a GET request on a virtual resource, for which  
                # the provider doesn't know the length 
                util.warn("Missing required Content-Length header in %s-response: closing connection" % statusCode)
                forceCloseConnection = True
            elif not type(currentContentLength) is str:
                util.warn("Invalid Content-Length header in response (%r): closing connection" % headerDict.get(b"content-length"))
                forceCloseConnection = True
            
            # HOTFIX for Vista and Windows 7 (issue 13, issue 23)
            # It seems that we must read *all* of the request body, otherwise
            # clients may miss the response.
            # For example Vista MiniRedir didn't understand a 401 response, 
            # when trying an anonymous PUT of big files. As a consequence, it
            # doesn't retry with credentials and the file copy fails. 
            # (XP is fine however).
            util.readAndDiscardInput(environ)

            # Make sure the socket is not reused, unless we are 100% sure all 
            # current input was consumed
            if(util.getContentLength(environ) != 0 
               and not environ.get(b"wsgidav.all_input_read")):
                util.warn("Input stream not completely consumed: closing connection")
                forceCloseConnection = True
                
            if forceCloseConnection and headerDict.get(b"connection") != b"close":
                util.warn("Adding 'Connection: close' header")
                response_headers.append((b"Connection", b"close"))
            
            # Log request
            if self._verbose >= 1:
                userInfo = environ.get(b"http_authenticator.username")
                if not userInfo:
                    userInfo = b"(anonymous)"
                threadInfo = b""
                if self._verbose >= 1:
                    threadInfo = b"<%s> " % threading._get_ident()
                extra = []
                if b"HTTP_DESTINATION" in environ:
                    extra.append(b'dest="%s"' % environ.get(b"HTTP_DESTINATION"))
                if environ.get(b"CONTENT_LENGTH", b"") != b"":
                    extra.append(b"length=%s" % environ.get(b"CONTENT_LENGTH"))
                if b"HTTP_DEPTH" in environ:
                    extra.append(b"depth=%s" % environ.get(b"HTTP_DEPTH"))
                if b"HTTP_RANGE" in environ:
                    extra.append(b"range=%s" % environ.get(b"HTTP_RANGE"))
                if b"HTTP_OVERWRITE" in environ:
                    extra.append(b"overwrite=%s" % environ.get(b"HTTP_OVERWRITE"))
                if self._verbose >= 1 and b"HTTP_EXPECT" in environ:
                    extra.append(b'expect="%s"' % environ.get(b"HTTP_EXPECT"))
                if self._verbose >= 2 and b"HTTP_CONNECTION" in environ:
                    extra.append(b'connection="%s"' % environ.get(b"HTTP_CONNECTION"))
                if self._verbose >= 2 and b"HTTP_USER_AGENT" in environ:
                    extra.append(b'agent="%s"' % environ.get(b"HTTP_USER_AGENT"))
                if self._verbose >= 2 and b"HTTP_TRANSFER_ENCODING" in environ:
                    extra.append(b'transfer-enc=%s' % environ.get(b"HTTP_TRANSFER_ENCODING"))
                if self._verbose >= 1:
                    extra.append(b'elap=%.3fsec' % (time.time() - start_time))
                extra = b", ".join(extra)
                        
#               This is the CherryPy format:     
#                127.0.0.1 - - [08/Jul/2009:17:25:23] "GET /loginPrompt?redirect=/renderActionList%3Frelation%3Dpersonal%26key%3D%26filter%3DprivateSchedule&reason=0 HTTP/1.1" 200 1944 "http://127.0.0.1:8002/command?id=CMD_Schedule" "Mozilla/5.0 (Windows; U; Windows NT 6.0; de; rv:1.9.1) Gecko/20090624 Firefox/3.5"
#                print >>sys.stderr, '%s - %s - [%s] "%s" %s -> %s' % (
                print(b'%s - %s - [%s] "%s" %s -> %s' % (
                                        threadInfo + environ.get(b"REMOTE_ADDR", b""),
                                        userInfo,
                                        util.getLogTime(), 
                                        environ.get(b"REQUEST_METHOD") + b" " + environ.get(b"PATH_INFO", b""),
                                        extra, 
                                        status,
#                                        response_headers.get(""), # response Content-Length
                                        # referer
                ), file=sys.stdout)

            # util.log("_start_response_wrapped CHECKPOINT 1.")

            return start_response(status, response_headers, exc_info)
            
        # Call next middleware
        try:
            app_iter = self._application(environ, _start_response_wrapper)
            for v in app_iter:
                yield v
            if hasattr(app_iter, b"close"):
                app_iter.close()
        except Exception as ex:
            # this should not happen, just in case.
            logger.error("Error in calling application: %r", ex, exc_info=True)
        finally:
            # commit batch if any.
            batch = environ.get(b'batch')
            if batch:
                batch.commit()
                del environ[b'batch']

        return
