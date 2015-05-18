# -*- coding: utf-8 -*-
"""
WSGI middleware to catch application thrown DAVErrors and return proper 
responses.

See `Developers info`_ for more information about the WsgiDAV architecture.

.. _`Developers info`: http://wsgidav.readthedocs.org/en/latest/develop.html  
"""
from __future__ import absolute_import, print_function, unicode_literals

__docformat__ = "reStructuredText"

import sys
import traceback
import logging

from . import util
from .dav_error import DAVError, getHttpStatusString, asDAVError,\
    HTTP_INTERNAL_ERROR, HTTP_NOT_MODIFIED, HTTP_NO_CONTENT

#_logger = util.getModuleLogger(__name__, defaultToVerbose=True)
_logger = logging.getLogger(__name__)
_logger.setLevel(logging.DEBUG)


class ErrorPrinter(object):

    def __init__(self, application, catchall=False):
        self._application = application
        self._catch_all_exceptions = catchall

    def __call__(self, environ, start_response):      
        # Intercept start_response
        sub_app_start_response = util.SubAppStartResponse()

        try:
            try:
                # request_server app may be a generator (for example the GET handler)
                # So we must iterate - not return self._application(..)!
                # Otherwise the we could not catch exceptions here. 
                response_started = False
                app_iter = self._application(environ, sub_app_start_response)
                for v in app_iter:
                    # Start response (the first time)
                    if not response_started:
                        # Success!
                        start_response(sub_app_start_response.status,
                                       sub_app_start_response.response_headers,
                                       sub_app_start_response.exc_info)
                    response_started = True

                    yield v

                # Close out iterator
                if hasattr(app_iter, b"close"):
                    app_iter.close()

                # Start response (if it hasn't been done yet)
                if not response_started:
                    # Success!
                    start_response(sub_app_start_response.status,
                                   sub_app_start_response.response_headers,
                                   sub_app_start_response.exc_info)

                return
            except DAVError, e:
                _logger.debug(b"re-raising %s" % e)
                raise
            except Exception, e:
                # Caught a non-DAVError 
                if self._catch_all_exceptions:
                    # Catch all exceptions to return as 500 Internal Error
                    #traceback.print_exc(10, environ.get(b"wsgi.errors") or sys.stderr)
                    traceback.print_exc(10, sys.stderr)
                    raise asDAVError(e)
                else:
                    util.warn(b"ErrorPrinter: caught Exception")
                    traceback.print_exc(10, sys.stderr) 
                    raise
        except DAVError, e:
            _logger.error(b"caught %s" % e)

            status = getHttpStatusString(e)
            # Dump internal errors to console
            if e.value == HTTP_INTERNAL_ERROR:
                print(b"ErrorPrinter: caught HTTPRequestException(HTTP_INTERNAL_ERROR)")
                traceback.print_exc(10, environ.get(b"wsgi.errors") or sys.stdout)
                print(b"e.srcexception:\n%s" % e.srcexception)
            elif e.value in (HTTP_NOT_MODIFIED, HTTP_NO_CONTENT):
#                util.log("ErrorPrinter: forcing empty error response for %s" % e.value)
                # See paste.lint: these code don't have content
                start_response(status, [(b"Content-Length", b"0"),
                                        (b"Date", util.getRfc1123Time()),
                                        ])
                yield b""
                return

            # If exception has pre-/post-condition: return as XML response, 
            # else return as HTML 
            content_type, body = e.getResponsePage()            

            # TODO: provide exc_info=sys.exc_info()?
            start_response(status, [(b"Content-Type", content_type),
                                    (b"Content-Length", str(len(body))),
                                    (b"Date", util.getRfc1123Time()),
                                    ])

            method = environ[b"REQUEST_METHOD"]
            if method == b'HEAD':
                # body should not be returned for HEAD request.
                yield b''
            else:
                yield body
            return
