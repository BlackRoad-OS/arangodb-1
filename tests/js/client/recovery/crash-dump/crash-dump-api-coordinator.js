/* jshint globalstrict:false, strict:false, unused : false */
/* global runSetup, assertEqual, assertTrue, assertNotEqual, arango */

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

// Test that crash dumps are created when a coordinator crashes and can be 
// retrieved via the crash dump API.

const jsunity = require('jsunity');
const IM = global.instanceManager;

if (runSetup === true) {
  'use strict';
  
  // Make some API calls before crash to ensure there's data to record
  arango.GET('/_api/version');
  arango.GET('/_api/database/current');
  
  // Verify no crashes exist before we crash
  const response = arango.GET('/_admin/server/crashes');
  if (!response.error && response.crashes && response.crashes.length !== 0) {
    throw new Error('Expected no crashes before setup, found: ' + JSON.stringify(response.crashes));
  }
  
  // Produce a crash on the coordinator (default target of debugTerminate)
  IM.debugTerminate();
  
  return 0;
}

// //////////////////////////////////////////////////////////////////////////////
// / @brief test suite
// //////////////////////////////////////////////////////////////////////////////

function recoverySuite () {
  'use strict';
  jsunity.jsUnity.attachAssertions();

  return {
    testCrashDumpCoordinatorCreatedAndAccessible: function () {
      // Check for crash dumps via API (goes to coordinator)
      const response = arango.GET('/_admin/server/crashes');
      assertTrue(!response.error, 'Should not return error: ' + JSON.stringify(response));
      assertEqual(200, response.code, 'Should return 200');

      const crashes = response.result || response;
      assertTrue(crashes.hasOwnProperty('crashes'), 'Should have crashes property');
      assertTrue(Array.isArray(crashes.crashes), 'crashes should be an array');

      // We should have exactly one crash now
      assertEqual(1, crashes.crashes.length,
                 'Expected exactly one crash dump, found: ' + crashes.crashes.length);

      // Get the crash
      const crashId = crashes.crashes[0];
      assertNotEqual(crashId, undefined, 'Crash ID should not be undefined');
      
      // Fetch crash contents
      const contentsResponse = arango.GET('/_admin/server/crashes/' + encodeURIComponent(crashId));
      assertTrue(!contentsResponse.error, 'Should get crash contents');
      assertEqual(200, contentsResponse.code, 'Should return 200 for crash contents');

      const contents = contentsResponse.result || contentsResponse;
      assertTrue(contents.hasOwnProperty('crashId'), 'Should have crashId');
      assertEqual(contents.crashId, crashId, 'crashId should match');
      assertTrue(contents.hasOwnProperty('files'), 'Should have files');

      // Assert specific expected files are present
      assertTrue(contents.files.hasOwnProperty('ApiRecording.json'), 
                 'Crash dump should contain ApiRecording.json');
      assertTrue(contents.files.hasOwnProperty('async-registry.json'), 
                 'Crash dump should contain async-registry.json');

      // Clean up - delete the crash
      const deleteResponse = arango.DELETE('/_admin/server/crashes/' + encodeURIComponent(crashId));
      assertTrue(!deleteResponse.error, 'Should delete crash');
      
      const deleteResult = deleteResponse.result || deleteResponse;
      assertTrue(deleteResult.deleted, 'Crash should be deleted');

      // Verify crash is gone
      const verifyResponse = arango.GET('/_admin/server/crashes');
      const verifyCrashes = verifyResponse.result || verifyResponse;
      assertEqual(0, verifyCrashes.crashes.length, 'Crash should be deleted');
    }
  };
}

// //////////////////////////////////////////////////////////////////////////////
// / @brief executes the test suite
// //////////////////////////////////////////////////////////////////////////////

jsunity.run(recoverySuite);
return jsunity.done();
