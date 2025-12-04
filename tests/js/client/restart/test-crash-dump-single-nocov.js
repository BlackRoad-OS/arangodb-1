/*jshint globalstrict:false, strict:false */
/* global assertTrue, assertEqual, assertNotEqual, arango */

// //////////////////////////////////////////////////////////////////////////////
// / DISCLAIMER
// /
// / Copyright 2014-2024 ArangoDB GmbH, Cologne, Germany
// / Copyright 2004-2014 triAGENS GmbH, Cologne, Germany
// /
// / Licensed under the Business Source License 1.1 (the "License");
// / you may not use this file except in compliance with the License.
// / You may obtain a copy of the License at
// /
// /     https://github.com/arangodb/arangodb/blob/devel/LICENSE
// /
// / Unless required by applicable law or agreed to in writing, software
// / distributed under the License is distributed on an "AS IS" BASIS,
// / WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// / See the License for the specific language governing permissions and
// / limitations under the License.
// /
// / Copyright holder is ArangoDB GmbH, Cologne, Germany
// /
// / @author Jure Bajic
// / @author Copyright 2025, ArangoDB GmbH, Cologne, Germany
// //////////////////////////////////////////////////////////////////////////////

// Test that crash dumps are created when the server crashes with SIGABRT.
// This test intentionally crashes the server and verifies the crash dump API.

const jsunity = require('jsunity');
const internal = require('internal');
const request = require('@arangodb/request');
const { time, sleep, killExternal, statusExternal, removePidFromMonitor } = internal;

const SIGABRT = 6;

let IM = global.instanceManager;

function CrashDumpSingleServerSuite() {
  'use strict';

  let waitForAlive = function(timeout, baseurl) {
    const end = time() + timeout;
    while (time() < end) {
      try {
        let res = request({ url: baseurl + '/_api/version', method: 'get', timeout: 1 });
        if (res.status === 200) {
          return true;
        }
      } catch (e) {
        // ignore connection errors during startup
      }
      sleep(0.5);
    }
    return false;
  };

  let getServer = function() {
    return IM.arangods.find(s => s.isRole('single'));
  };

  return {
    testCrashDumpCreatedOnSIGABRT: function() {
      let server = getServer();
      assertTrue(server !== undefined, 'Could not find single server');

      // Assert no crashes exist at the start
      let initialResponse = arango.GET('/_admin/server/crashes');
      assertEqual(200, initialResponse.code, 'Should get crashes list');
      assertTrue(initialResponse.result.hasOwnProperty('crashes'), 'Should have crashes property');
      assertEqual(0, initialResponse.result.crashes.length, 
                  'Expected no crashes at test start, found: ' + 
                  JSON.stringify(initialResponse.result.crashes));

      // Make some API calls before crash to ensure there's data to record
      arango.GET('/_api/version');
      arango.GET('/_api/database/current');

      let oldPid = server.pid;
      console.warn('Sending SIGABRT to server pid: ' + oldPid);

      // Remove from monitor BEFORE killing to avoid "unexpected child death" detection
      if (server.options && server.options.enableAliveMonitor) {
        removePidFromMonitor(oldPid);
      }
      
      // Mark server as suspended/crashed so the framework doesn't treat it as unexpected
      server.suspended = true;

      // Kill the server with SIGABRT to trigger crash handler
      killExternal(oldPid, SIGABRT);

      // Wait for the server to die by polling statusExternal
      let exitStatus = null;
      let count = 0;
      while (count < 120) {
        let status = statusExternal(oldPid, false);
        if (status.status !== 'RUNNING') {
          exitStatus = status;
          break;
        }
        sleep(0.5);
        count++;
      }

      assertTrue(exitStatus !== null, 'Server did not die in time');
      console.warn('Server exited with status: ' + JSON.stringify(exitStatus));

      // Update server state for restart
      server.exitStatus = exitStatus;
      server.pid = null;
      // Mark that we expect this crash - don't count it as a test failure
      server.serverCrashedLocal = false;

      // Restart the server
      console.warn('Restarting server...');
      server.restartOneInstance({});
      server.suspended = false;

      // Wait for server to be alive
      assertTrue(waitForAlive(120, server.url), 'Server did not restart in time');

      // Reconnect arango client to the restarted server
      arango.reconnect(server.endpoint, '_system', 'root', '');

      // Now check for crash dumps
      let response = arango.GET('/_admin/server/crashes');
      assertTrue(!response.error, 'Should not return error: ' + JSON.stringify(response));
      assertEqual(response.code, 200, 'Should return 200');

      let crashes = response.result;
      assertTrue(crashes.hasOwnProperty('crashes'), 'Should have crashes property');
      assertTrue(Array.isArray(crashes.crashes), 'crashes should be an array');

      // We should have exactly one crash now
      assertEqual(1, crashes.crashes.length,
                 'Expected exactly one crash dump, found: ' + crashes.crashes.length);

      // Get the crash
      let crashId = crashes.crashes[0];
      assertNotEqual(crashId, undefined, 'Crash ID should not be undefined');
      console.warn('Found crash dump with ID: ' + crashId);

      // Fetch crash contents
      let contentsResponse = arango.GET('/_admin/server/crashes/' + encodeURIComponent(crashId));
      assertTrue(!contentsResponse.error, 'Should get crash contents');
      assertEqual(contentsResponse.code, 200, 'Should return 200 for crash contents');

      let contents = contentsResponse.result;
      assertTrue(contents.hasOwnProperty('crashId'), 'Should have crashId');
      assertEqual(contents.crashId, crashId, 'crashId should match');
      assertTrue(contents.hasOwnProperty('files'), 'Should have files');
      console.warn('Crash contains files: ' + Object.keys(contents.files).join(', '));

      // Assert specific expected files are present
      assertTrue(contents.files.hasOwnProperty('ApiRecording.json'), 
                 'Crash dump should contain ApiRecording.json');
      assertTrue(contents.files.hasOwnProperty('async-registry.json'), 
                 'Crash dump should contain async-registry.json');

      // Clean up - delete the crash
      let deleteResponse = arango.DELETE('/_admin/server/crashes/' + encodeURIComponent(crashId));
      assertTrue(!deleteResponse.error, 'Should delete crash');
      assertTrue(deleteResponse.result.deleted, 'Crash should be deleted');

      console.warn('Test passed - crash dump was created and retrieved successfully');
    },
  };
}

jsunity.run(CrashDumpSingleServerSuite);
return jsunity.done();
