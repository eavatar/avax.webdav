# -*- coding: utf-8 -*-
"""
WSGI middleware used for debugging (optional).

This module dumps request and response information to the console, depending
on current debug configuration.

On init:
    Define HTTP methods and litmus tests, that should turn on the verbose mode
    (currently hard coded).              
For every request:
    Increase value of ``environ['verbose']``, if the request should be debugged.
    Also dump request and response headers and body.
    
    Then pass the request to the next middleware.  

These configuration settings are evaluated:

*verbose*
    This is also used by other modules. This filter adds additional information
    depending on the value.

    =======  ===================================================================
    verbose  Effect  
    =======  ===================================================================
     0        No additional output.
     1        No additional output (only standard request logging).
     2        Dump headers of all requests and responses.
     3        Dump headers and bodies of all requests and responses. 
    =======  ===================================================================

*debug_methods*
    Boost verbosity to 3 while processing certain request methods. This option 
    is ignored, when ``verbose < 2``.

    Configured like::

        debug_methods = ["PROPPATCH", "PROPFIND", "GET", "HEAD","DELETE",
                         "PUT", "COPY", "MOVE", "LOCK", "UNLOCK",
                         ]
 
*debug_litmus*
    Boost verbosity to 3 while processing litmus tests that contain certain 
    substrings. This option is ignored, when ``verbose < 2``.

    Configured like::
    
        debug_litmus = ["notowner_modify", "props: 16", ]

 
See `Developers info`_ for more information about the WsgiDAV architecture.

.. _`Developers info`: http://wsgidav.readthedocs.org/en/latest/develop.html  
"""
from __future__ import absolute_import, division, print_function, \
    unicode_literals

from ..wsgidav import util
import sys
import threading

__docformat__ = "reStructuredText"


class WsgiDavDebugFilter(object):

    def __init__(self, application, config):
        self._application = application
        self._config = config
#        self.out = sys.stderr
        self.out = sys.stdout
        self.passedLitmus = {}
        # These methods boost verbose=2 to verbose=3
        self.debug_methods = config.get(b"debug_methods", [])
        # Litmus tests containing these string boost verbose=2 to verbose=3
        self.debug_litmus = config.get(b"debug_litmus", [])
        # Exit server, as soon as this litmus test has finished
        self.break_after_litmus = [
#                                   "locks: 15",
                                   ]

    def __call__(self, environ, start_response):
        """"""
#        srvcfg = environ[b"wsgidav.config"]
        verbose = self._config.get(b"verbose", 2)

        method = environ[b"REQUEST_METHOD"]

        debugBreak = False
        dumpRequest = False
        dumpResponse = False
        
        if verbose >= 3:
            dumpRequest = dumpResponse = True

        # Process URL commands
        if b"dump_storage" in environ.get(b"QUERY_STRING"):
            dav = environ.get(b"wsgidav.provider")
            if dav.lockManager:
                dav.lockManager._dump()
            if dav.propManager:
                dav.propManager._dump()

        # Turn on max. debugging for selected litmus tests
        litmusTag = environ.get(b"HTTP_X_LITMUS", environ.get(b"HTTP_X_LITMUS_SECOND"))
        if litmusTag and verbose >= 2:
            print(b"----\nRunning litmus test '%s'..." % litmusTag, file=self.out)
            for litmusSubstring in self.debug_litmus: 
                if litmusSubstring in litmusTag:
                    verbose = 3
                    debugBreak = True
                    dumpRequest = True
                    dumpResponse = True
                    break
            for litmusSubstring in self.break_after_litmus:
                if litmusSubstring in self.passedLitmus and litmusSubstring not in litmusTag:
                    print(b" *** break after litmus %s" % litmusTag, file=self.out)
                    sys.exit(-1)
                if litmusSubstring in litmusTag:
                    self.passedLitmus[litmusSubstring] = True
                
        # Turn on max. debugging for selected request methods
        if verbose >= 2 and method in self.debug_methods:
            verbose = 3
            debugBreak = True
            dumpRequest = True
            dumpResponse = True

        # Set debug options to environment
        environ[b"wsgidav.verbose"] = verbose
#        environ[b"wsgidav.debug_methods"] = self.debug_methods
        environ[b"wsgidav.debug_break"] = debugBreak
        environ[b"wsgidav.dump_request_body"] = dumpRequest
        environ[b"wsgidav.dump_response_body"] = dumpResponse

        # Dump request headers
        if dumpRequest:      
            print(b"<%s> --- %s Request ---" % (threading._get_ident(), method),
                  file=self.out)
            for k, v in environ.items():
                if k == k.upper():
                    print(b"%20s: '%s'" % (k, v), file=self.out)
            print(b"\n", file=self.out)

        # Intercept start_response
        #
        sub_app_start_response = util.SubAppStartResponse()

        nbytes = 0
        first_yield = True
        app_iter = self._application(environ, sub_app_start_response)

        for v in app_iter:
            # Start response (the first time)
            if first_yield:
                # Success!
                start_response(sub_app_start_response.status,
                               sub_app_start_response.response_headers,
                               sub_app_start_response.exc_info)

            # Dump response headers
            if first_yield and dumpResponse:
                print(b"<%s> --- %s Response(%s): ---"
                      % (threading._get_ident(),
                         method,
                         sub_app_start_response.status),
                      file=self.out)
                headersdict = dict(sub_app_start_response.response_headers)
                for envitem in headersdict.keys():
                    print(b"%s: %s" % (envitem, repr(headersdict[envitem])),
                          file=self.out)
                print(b"", file=self.out)

            # Check, if response is a binary string, otherwise we probably have 
            # calculated a wrong content-length

            if type(v) is not str:
                print("type(v): %r" % type(v))
                print("%r" % v)

            assert type(v) is str
            
            # Dump response body
            drb = environ.get(b"wsgidav.dump_response_body")
            if type(drb) is str:
                # Middleware provided a formatted body representation 
                print(drb, file=self.out)
                drb = environ[b"wsgidav.dump_response_body"] = None
            elif drb is True:
                # Else dump what we get, (except for long GET responses) 
                if method == b"GET":
                    if first_yield:
                        print(v[:50], b"...", file=self.out)
                elif len(v) > 0:
                    print(v, file=self.out)

            nbytes += len(v) 
            first_yield = False
            yield v
        if hasattr(app_iter, b"close"):
            app_iter.close()

        # Start response (if it hasn't been done yet)
        if first_yield:
            # Success!
            start_response(sub_app_start_response.status,
                           sub_app_start_response.response_headers,
                           sub_app_start_response.exc_info)

        if dumpResponse:
            print(b"\n<%s> --- End of %s Response (%i bytes) ---" % (threading._get_ident(), method, nbytes), file=self.out)
        return 
