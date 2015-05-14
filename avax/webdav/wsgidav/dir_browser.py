# -*- coding: utf-8 -*-
"""
WSGI middleware that handles GET requests on collections to display directories.

See `Developers info`_ for more information about the WsgiDAV architecture.

.. _`Developers info`: http://wsgidav.readthedocs.org/en/latest/develop.html  
"""
from __future__ import absolute_import, print_function, unicode_literals

import os
import sys
import urllib

from . import util
from ..wsgidav.dav_error import DAVError, HTTP_OK, HTTP_MEDIATYPE_NOT_SUPPORTED
from ..wsgidav.version import __version__

__docformat__ = "reStructuredText"



msOfficeTypeToExtMap = {
    b"excel": (b"xls", b"xlt", b"xlm", b"xlsm", b"xlsx", b"xltm", b"xltx"),
    b"powerpoint": (b"pps", b"ppt", b"pptm", b"pptx", b"potm", b"potx", b"ppsm", b"ppsx"),
    b"word": (b"doc", b"dot", b"docm", b"docx", b"dotm", b"dotx"),
    b"visio": (b"vsd", b"vsdm", b"vsdx", b"vstm", b"vstx"),
}
msOfficeExtToTypeMap = {}
for t, el in msOfficeTypeToExtMap.iteritems():
    for e in el:
        msOfficeExtToTypeMap[e] = t


PAGE_CSS = b"""\
    img { border: 0; padding: 0 2px; vertical-align: text-bottom; }
    th, td { padding: 2px 20px 2px 2px; }
    th { text-align: left; }
    th.right { text-align: right; }
    td  { font-family: monospace; vertical-align: bottom; white-space: pre; }
    td.right { text-align: right; }
    table { border: 0; }
    a.symlink { font-style: italic; }
    p.trailer { font-size: smaller; }
"""


PAGE_SCRIPT = b"""\
function onLoad() {
//    console.log("loaded.");
}

/* Event delegation handler for clicks on a-tags with class 'msoffice'. */
function onClickTable(event) {
    var target = event.target || event.srcElement,
        href = target.href;
    
    if( href && target.className === "msoffice" ){
        if( openWithSharePointPlugin(href) ){
            // prevent default processing
            return false;        
        }
    }
}

function openWithSharePointPlugin(url) {
    var res = false,
        control = null,
        isFF = false;

    // Get the most recent version of the SharePoint plugin
    if( window.ActiveXObject ){
        try {
            control = new ActiveXObject("SharePoint.OpenDocuments.3"); // Office 2007
        } catch(e) {
            try {
                control = new ActiveXObject("SharePoint.OpenDocuments.2"); // Office 2003
            } catch(e2) {
                try {
                    control = new ActiveXObject("SharePoint.OpenDocuments.1"); // Office 2000/XP
                } catch(e3) {
                    window.console && console.warn("Could not create ActiveXObject('SharePoint.OpenDocuments'). Check your browsers security settings.");
                    return false;
                }
            }
        }
        if( !control ){
            window.console && console.warn("Cannot instantiate the required ActiveX control to open the document. This is most likely because you do not have Office installed or you have an older version of Office.");
        }
    } else {
        window.console && console.log("Non-IE: using FFWinPlugin Plug-in...");
        control = document.getElementById("winFirefoxPlugin");
        isFF = true;
    }

    try {
//      window.console && console.log("SharePoint.OpenDocuments.EditDocument('" + url + "')...");
        res = control.EditDocument(url);
//      window.console && console.log("SharePoint.OpenDocuments.EditDocument('" + url + "')... res = ", res);
        if( !res ){
            window.console && console.warn("SharePoint.OpenDocuments.EditDocument('" + url + "') returned false.");
        }
    } catch (e){
        window.console && console.warn("SharePoint.OpenDocuments.EditDocument('" + url + "') failed.", e);
    }
    return res;
}
"""


class WsgiDavDirBrowser(object):
    """WSGI middleware that handles GET requests on collections to display directories."""

    def __init__(self, application):
        self._application = application
        self._verbose = 2

    def __call__(self, environ, start_response):
        path = environ[b"PATH_INFO"]
        
        davres = None
        if environ[b"wsgidav.provider"]:
            davres = environ[b"wsgidav.provider"].getResourceInst(path, environ)

        if environ[b"REQUEST_METHOD"] in (b"GET", b"HEAD") and davres and davres.isCollection:

#            if "mozilla" not in environ.get("HTTP_USER_AGENT").lower():
#                # issue 14: Nautilus sends GET on collections
#                # http://code.google.com/p/wsgidav/issues/detail?id=14
#                util.status("Directory browsing disabled for agent '%s'" % environ.get("HTTP_USER_AGENT"))
#                self._fail(HTTP_NOT_IMPLEMENTED)
#                return self._application(environ, start_response)

            if util.getContentLength(environ) != 0:
                self._fail(HTTP_MEDIATYPE_NOT_SUPPORTED,
                           b"The server does not handle any body content.")
            
            if environ[b"REQUEST_METHOD"] == b"HEAD":
                return util.sendStatusResponse(environ, start_response, HTTP_OK)

            # Support DAV mount (http://www.ietf.org/rfc/rfc4709.txt)
            dirConfig = environ[b"wsgidav.config"].get(b"dir_browser", {})
            if dirConfig.get(b"davmount") and b"davmount" in environ.get(b"QUERY_STRING"):
#                collectionUrl = davres.getHref()
                collectionUrl = util.makeCompleteUrl(environ)
                collectionUrl = collectionUrl.split(b"?")[0]
                res = b"""
                    <dm:mount xmlns:dm="http://purl.org/NET/webdav/mount">
                        <dm:url>%s</dm:url>
                    </dm:mount>""" % (collectionUrl)
                # TODO: support <dm:open>%s</dm:open>

                start_response(b"200 OK", [(b"Content-Type", b"application/davmount+xml"),
                                          (b"Content-Length", str(len(res))),
                                          (b"Cache-Control", b"private"),
                                          (b"Date", util.getRfc1123Time()),
                                          ])
                return [ res ]
            
            # Profile calls
#            if True:
#                from cProfile import Profile
#                profile = Profile()
#                profile.runcall(self._listDirectory, environ, start_response)
#                # sort: 0:"calls",1:"time", 2: "cumulative"
#                profile.print_stats(sort=2)
            return self._listDirectory(davres, environ, start_response)
        
        return self._application(environ, start_response)

    def _fail(self, value, contextinfo=None, srcexception=None, errcondition=None):
        """Wrapper to raise (and log) DAVError."""
        e = DAVError(value, contextinfo, srcexception, errcondition)
        if self._verbose >= 2:
            print(b"Raising DAVError %s" % e.getUserInfo(), file=sys.stdout)
        raise e

    def _listDirectory(self, davres, environ, start_response):
        """
        @see: http://www.webdav.org/specs/rfc4918.html#rfc.section.9.4
        """
        assert davres.isCollection
        
        dirConfig = environ[b"wsgidav.config"].get(b"dir_browser", {})
        displaypath = urllib.unquote(davres.getHref())
        isReadOnly = environ[b"wsgidav.provider"].isReadOnly()


        trailer = dirConfig.get(b"response_trailer")
        if trailer:
            trailer = trailer.replace(b"${version}",
                b"<a href='https://github.com/mar10/wsgidav/'>WsgiDAV/%s</a>" % __version__)
            trailer = trailer.replace(b"${time}", util.getRfc1123Time())
        else:
            trailer = (b"%s" % (util.getRfc1123Time()))
        
        html = []
        html.append(b"<!DOCTYPE HTML PUBLIC '-//W3C//DTD HTML 4.01//EN' 'http://www.w3.org/TR/html4/strict.dtd'>")
        html.append(b"<html>")
        html.append(b"<head>")
        html.append(b"<meta http-equiv='Content-Type' content='text/html; charset=UTF-8'>")
        html.append(b"<meta name='generator' content='WsgiDAV %s'>" % __version__)
        html.append(b"<title>WsgiDAV - Index of %s </title>" % displaypath)
        
        html.append(b"<script type='text/javascript'>%s</script>" % PAGE_SCRIPT)
        html.append(b"<style type='text/css'>%s</style>" % PAGE_CSS)

        # Special CSS to enable MS Internet Explorer behaviour
        if dirConfig.get(b"ms_mount"):
            html.append(b"<style type='text/css'> A {behavior: url(#default#AnchorClick);} </style>")
        
        if dirConfig.get(b"ms_sharepoint_plugin"):
            html.append(b"<object id='winFirefoxPlugin' type='application/x-sharepoint' width='0' height='0' style=''visibility: hidden;'></object>")

        html.append(b"</head>")
        html.append(b"<body onload='onLoad()'>")

        # Title
        html.append(b"<h1>Index of %s</h1>" % displaypath)
        # Add DAV-Mount link and Web-Folder link
        links = []
        if dirConfig.get(b"davmount"):
            links.append(b"<a title='Open this folder in a WebDAV client.' href='%s?davmount'>Mount</a>" % util.makeCompleteUrl(environ))
        if dirConfig.get(b"ms_mount"):
            links.append(b"<a title='Open as Web Folder (requires Microsoft Internet Explorer)' href='' FOLDER='%s'>Open as Web Folder</a>" % util.makeCompleteUrl(environ))
#                html.append(b"<a href='' FOLDER='%ssetup.py'>Open setup.py as WebDAV</a>" % util.makeCompleteUrl(environ))
        if links:
            html.append(b"<p>%s</p>" % b" &#8211; ".join(links))

        html.append(b"<hr>")
        # Listing
        html.append(b"<table onclick='return onClickTable(event)'>")

        html.append(b"<thead>")
        html.append(b"<tr><th>Name</th> <th>Type</th> <th class='right'>Size</th> <th class='right'>Last modified</th> </tr>")
        html.append(b"</thead>")
            
        html.append(b"<tbody>")
        if davres.path in (b"", b"/"):
            html.append(b"<tr><td>Top level share</td> <td></td> <td></td> <td></td> </tr>")
        else:
            parentUrl = util.getUriParent(davres.getHref())
            html.append(b"<tr><td><a href='" + parentUrl + b"'>Parent Directory</a></td> <td></td> <td></td> <td></td> </tr>")

        # Ask collection for member info list
        dirInfoList = davres.getDirectoryInfo()

        if dirInfoList is None:
            # No pre-build info: traverse members
            dirInfoList = []
            childList = davres.getDescendants(depth=b"1", addSelf=False)
            for res in childList:
                di = res.getDisplayInfo()
                href = res.getHref()
                infoDict = {b"href": href,
                            b"class": b"",
                            b"displayName": res.getDisplayName(),
                            b"lastModified": res.getLastModified(),
                            b"isCollection": res.isCollection,
                            b"contentLength": res.getContentLength(),
                            b"displayType": di.get(b"type"),
                            b"displayTypeComment": di.get(b"typeComment"),
                            }

                if not isReadOnly and not res.isCollection:
                    ext = os.path.splitext(href)[1].lstrip(b".").lower()
                    officeType = msOfficeExtToTypeMap.get(ext)
                    if officeType:
                        print(b"OT", officeType)
                        print(b"OT", dirConfig)
                        if dirConfig.get(b"ms_sharepoint_plugin"):
                            infoDict[b"class"] = b"msoffice"
                        elif dirConfig.get(b"ms_sharepoint_urls"):
                            infoDict[b"href"] = b"ms-%s:ofe|u|%s" % (officeType, href)

                dirInfoList.append(infoDict)
        # 
        for infoDict in dirInfoList:
            lastModified = infoDict.get(b"lastModified")
            if lastModified is None:
                infoDict[b"strModified"] = b""
            else:
                infoDict[b"strModified"] = util.getRfc1123Time(lastModified)
            
            infoDict[b"strSize"] = b"-"
            if not infoDict.get(b"isCollection"):
                contentLength = infoDict.get(b"contentLength")
                if contentLength is not None:
                    infoDict[b"strSize"] = util.byteNumberString(contentLength)

            html.append(b"""\
            <tr><td><a href="%(href)s" class="%(class)s">%(displayName)s</a></td>
            <td>%(displayType)s</td>
            <td class='right'>%(strSize)s</td>
            <td class='right'>%(strModified)s</td></tr>""" % infoDict)
            
        html.append(b"</tbody>")
        html.append(b"</table>")

        html.append(b"<hr>")

        if b"http_authenticator.username" in environ:
            if environ.get(b"http_authenticator.username"):
                html.append(b"<p>Authenticated user: '%s', realm: '%s'.</p>"
                            % (environ.get(b"http_authenticator.username"),
                               environ.get(b"http_authenticator.realm")))
#            else:
#                html.append("<p>Anonymous</p>")

        if trailer:
            html.append(b"<p class='trailer'>%s</p>" % trailer)

        html.append(b"</body></html>")
        body = b"\n".join(html)
        start_response(b"200 OK", [(b"Content-Type", b"text/html"),
                                   (b"Content-Length", str(len(body))),
                                   (b"Date", util.getRfc1123Time()),
                                   ])
        return [body]
