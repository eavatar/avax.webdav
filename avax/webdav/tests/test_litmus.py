# -*- coding: iso-8859-1 -*-
# (c) 2009-2014 Martin Wendt and contributors; see WsgiDAV https://github.com/mar10/wsgidav
# Licensed under the MIT license: http://www.opensource.org/licenses/mit-license.php
"""
    Run litmus against WsgiDAV server.
"""
from tempfile import gettempdir
import os
import unittest
import subprocess
from multiprocessing.process import Process
import time

from avax.repository.blocks.store import MockBlockStore
from avax.repository.objects.store import ObjectStore
from avax.repository.objects.repo import Repository

from avax.webdav.wsgidav.wsgidav_app import DEFAULT_CONFIG, WsgiDAVApp
from avax.webdav.wsgidav.fs_dav_provider import FilesystemProvider
from avax.webdav.archive_provider import ArchiveProvider


def run_wsgidav_server(with_auth, with_ssl):
    """Start blocking WsgiDAV server (called as a separate process)."""
    package_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    share_path = os.path.join(gettempdir(), "wsgidav-test")
    if not os.path.exists(share_path):
        os.mkdir(share_path)
    object_store = ObjectStore(MockBlockStore())
    repository = Repository(object_store)

    provider = ArchiveProvider(repository, b'files')
    fs_provider = FilesystemProvider(share_path)

    config = DEFAULT_CONFIG.copy()
    config.update({
        "host": "127.0.0.1",
        "port": 8080,
        "provider_mapping": {"/": provider},
        "user_mapping": {},
        "verbose": 1,
        "enable_loggers": [],
        "propsmanager": True,      # None: no property manager
        "locksmanager": True,      # True: use lock_manager.LockManager
        "domaincontroller": None,  # None: domain_controller.WsgiDAVDomainController(user_mapping)
        })

    if with_auth:
        config.update({
            "user_mapping": {"/": {"tester": {"password": "secret",
                                              "description": "",
                                              "roles": [],
                                              },
                                       },
                                 },
            "acceptbasic": True,
            "acceptdigest": False,
            "defaultdigest": False,
            })

    if with_ssl:
        config.update({
            "ssl_certificate": os.path.join(package_path, "wsgidav/server/sample_bogo_server.crt"),
            "ssl_private_key": os.path.join(package_path, "wsgidav/server/sample_bogo_server.key"),
            "ssl_certificate_chain": None,
            # "acceptdigest": True,
            # "defaultdigest": True,
            })

    app = WsgiDAVApp(config)

    from avax.webdav.wsgidav.server.run_server import _runBuiltIn
    _runBuiltIn(app, config, None)
    # blocking...



#===============================================================================
# WsgiDAVServerTest
#===============================================================================

class WsgiDAVLitmusTest(unittest.TestCase):
    """Test the built-in WsgiDAV server with cadaver."""

    def setUp(self):
        pass

    def tearDown(self):
        pass


    ############################################################################

    def test_litmus_with_authentication(self):
        """Run litmus test suite on HTTP with authentification.

        This test passes
        """
        try:
            proc = Process(target=run_wsgidav_server, args=(True, False))
            proc.daemon = True
            proc.start()
            time.sleep(1)

            try:
                self.assertEqual(subprocess.call(["litmus", "http://127.0.0.1:8080/", "tester", "secret"]),
                                 0,
                                 "litmus suite failed: check the log")
            except OSError:
                print "*" * 70
                print "This test requires the litmus test suite."
                print "See http://www.webdav.org/neon/litmus/"
                print "*" * 70
                raise

        finally:
            proc.terminate()
            proc.join()


    ############################################################################


    # The test with anonymous access fails here:
    #
#  0. init.................. pass
#  1. begin................. pass
#  2. expect100............. FAIL (timeout waiting for interim response)
#  3. finish................ pass

    # def test_litmus_anonymous(self):
    #     """Run litmus test suite as anonymous."""
    #     try:
    #         proc = Process(target=run_wsgidav_server, args=(False, False))
    #         proc.daemon = True
    #         proc.start()
    #         time.sleep(1)

    #         try:
    #             self.assertEqual(subprocess.call(["litmus", "http://localhost:8080/"]),
    #                              0,
    #                              "litmus suite failed: check the log")
    #         except OSError:
    #             print "This test requires the litmus test suite."
    #             print "See http://www.webdav.org/neon/litmus/"
    #             raise

    #     finally:
    #         proc.terminate()
    #         proc.join()


    ############################################################################


    # def test_litmus_with_ssl_and_authentication(self):
    #     """Run litmus test suite on SSL / HTTPS with authentification."""

    #     try:
    #         proc = Process(target=run_wsgidav_server, args=(True, True))
    #         proc.daemon = True
    #         proc.start()
    #         time.sleep(1)

    #         try:
    #             self.assertEqual(subprocess.call(["litmus", "https://127.0.0.1:8080/", "tester", "secret"]),
    #                              0,
    #                              "litmus suite failed: check the log")
    #         except OSError:
    #             print "*" * 70
    #             print "This test requires the litmus test suite."
    #             print "See http://www.webdav.org/neon/litmus/"
    #             print "*" * 70
    #             raise

    #     finally:
    #         proc.terminate()
    #         proc.join()


#===============================================================================
# suite
#===============================================================================

if __name__ == "__main__":
    unittest.main()
