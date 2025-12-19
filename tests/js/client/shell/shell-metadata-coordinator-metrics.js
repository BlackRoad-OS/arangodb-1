/*jshint globalstrict:false, strict:false */
/*global arango, assertTrue, assertEqual, assertNotEqual, fail */

// //////////////////////////////////////////////////////////////////////////////
// / DISCLAIMER
// /
// / Copyright 2025 ArangoDB Hyderabad, India
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
// / @author Avanthi Dundigala
// //////////////////////////////////////////////////////////////////////////////

const jsunity = require("jsunity");
const arangodb = require("@arangodb");
const db = arangodb.db;
const internal = require('internal');
const isCluster = internal.isCluster();
const { getMetric, getEndpointsByType, moveShard } = require("@arangodb/test-helper");

function metadataCoordinatorMetricsSuite() {
  'use strict';
  const testDbName = "testMetricsCoordinator";
  const testCollectionName = "testMetricsCollection";

  const isClusterMode = isCluster;

  const assertMetrics = function(endpoints, expectedDatabases, expectedCollections, expectedShards) {
    const retries = isClusterMode ? 3 : 1;

    endpoints.forEach((ep) => {
      let numDatabases = getMetric(ep, "arangodb_metadata_number_of_databases");
      let numCollections = getMetric(ep, "arangodb_metadata_number_of_collections");
      let numShards = isClusterMode ? getMetric(ep, "arangodb_metadata_number_of_shards") : 0;

      for (let i = 0; i < retries; ++i) {
        if (isClusterMode) {
          internal.sleep(1);
        }

        numDatabases = getMetric(ep, "arangodb_metadata_number_of_databases");
        if (numDatabases !== expectedDatabases) {
          continue;
        }

        numCollections = getMetric(ep, "arangodb_metadata_number_of_collections");
        if (numCollections !== expectedCollections) {
          continue;
        }

        if (isClusterMode) {
          numShards = getMetric(ep, "arangodb_metadata_number_of_shards");
          if (numShards !== expectedShards) {
            continue;
          }
        }

        break; // all matched
      }

      assertEqual(numDatabases, expectedDatabases,
                  `Number of databases found: ${numDatabases}, expected: ${expectedDatabases}`);
      assertEqual(numCollections, expectedCollections,
                  `Number of collections found: ${numCollections}, expected: ${expectedCollections}`);
      if (isClusterMode) {
        assertEqual(numShards, expectedShards,
                    `Number of shards found: ${numShards}, expected: ${expectedShards}`);
      }
    });
  };

  return {
    tearDown: function() {
      try {
        db._useDatabase("_system");
        db._dropDatabase(testDbName);
      } catch (err) {
        // ignore
      }
    },

    testMetricsSimple: function() {
      let endpoints;
      if (isClusterMode) {
        endpoints = getEndpointsByType('coordinator');
      } else {
        endpoints = getEndpointsByType('single');
      }
      assertTrue(endpoints.length > 0);
      assertMetrics(endpoints, 1, 12, 12);
    },

    testCoordinatorNewMetricsExistAndMatchShards: function() {
      if (!isClusterMode) return;
      const endpoints = getEndpointsByType('coordinator');
      assertTrue(endpoints.length > 0);
      endpoints.forEach((ep) => {
        let total = getMetric(ep, "arangodb_metadata_total_number_of_shards");
        let planShards = getMetric(ep, "arangodb_metadata_number_of_shards");
        for (let i = 0; i < 3 && total !== planShards; ++i) {
          internal.sleep(1);
          total = getMetric(ep, "arangodb_metadata_total_number_of_shards");
          planShards = getMetric(ep, "arangodb_metadata_number_of_shards");
        }
        assertEqual(total, planShards,
                    `coordinator total shards (${total}) must match metadata shards (${planShards})`);
      });
    },

    testCoordinatorMetricsAfterCreatingReplicatedCollection: function() {
      if (!isClusterMode) return;
      const endpoints = getEndpointsByType('coordinator');
      assertTrue(endpoints.length > 0);
      const ep = endpoints[0];

      const baseTotal = getMetric(ep, "arangodb_metadata_total_number_of_shards");
      const baseFollowers = getMetric(ep, "arangodb_metadata_number_follower_shards");

      db._createDatabase(testDbName);
      db._useDatabase(testDbName);
      db._create(testCollectionName, { numberOfShards: 5, replicationFactor: 3 });

      const expectedTotal = baseTotal + 5;
      const expectedFollowers = baseFollowers + 10; // 5 * (3-1)

      let total = 0, followers = 0;
      for (let i = 0; i < 8; ++i) {
        internal.sleep(1);
        total = getMetric(ep, "arangodb_metadata_total_number_of_shards");
        followers = getMetric(ep, "arangodb_metadata_number_follower_shards");
        if (total === expectedTotal && followers === expectedFollowers) break;
      }

      assertEqual(total, expectedTotal, `total shards after create: ${total}, expected ${expectedTotal}`);
      assertEqual(followers, expectedFollowers, `follower shards after create: ${followers}, expected ${expectedFollowers}`);

      // cleanup
      db._drop(testCollectionName);
      db._useDatabase("_system");
      db._dropDatabase(testDbName);
    },

    testCoordinatorMetricsNotReplicatedCount: function() {
      if (!isClusterMode) return;
      const endpoints = getEndpointsByType('coordinator');
      assertTrue(endpoints.length > 0);
      const ep = endpoints[0];

      const baseNotRep = getMetric(ep, "arangodb_metadata_number_not_replicated_shards");

      db._createDatabase(testDbName);
      db._useDatabase(testDbName);
      db._create(testCollectionName, { numberOfShards: 4, replicationFactor: 1 });

      const expectedNotRep = baseNotRep + 4;

      let notrep = 0;
      for (let i = 0; i < 8; ++i) {
        internal.sleep(1);
        notrep = getMetric(ep, "arangodb_metadata_number_not_replicated_shards");
        if (notrep === expectedNotRep) break;
      }

      assertEqual(notrep, expectedNotRep, `not replicated shards: ${notrep}, expected ${expectedNotRep}`);

      // cleanup
      db._drop(testCollectionName);
      db._useDatabase("_system");
      db._dropDatabase(testDbName);
    },

    testCoordinatorFollowerCountStableOnMove: function() {
      if (!isClusterMode) return;
      const endpoints = getEndpointsByType('coordinator');
      assertTrue(endpoints.length > 0);
      const ep = endpoints[0];

      db._createDatabase(testDbName);
      db._useDatabase(testDbName);
      const col = db._create(testCollectionName, { numberOfShards: 3, replicationFactor: 3 });

      // baseline follower
      const baseFollowers = getMetric(ep, "arangodb_metadata_number_follower_shards");

      const shards = col.shards(true);
      const shardId = Object.keys(shards)[0];
      const fromServer = shards[shardId][0];
      const toServer = shards[shardId][1];
      assertNotEqual(fromServer, toServer);

      const moved = moveShard(testDbName, testCollectionName, shardId, fromServer, toServer, false);
      assertTrue(moved);

      let followers = 0;
      for (let i = 0; i < 12; ++i) {
        internal.sleep(1);
        followers = getMetric(ep, "arangodb_metadata_number_follower_shards");
        if (followers === baseFollowers) break;
      }

      assertEqual(followers, baseFollowers, `followers after move: ${followers}, expected ${baseFollowers}`);

      // cleanup
      db._drop(testCollectionName);
      db._useDatabase("_system");
      db._dropDatabase(testDbName);
    }
  };
}

jsunity.run(metadataCoordinatorMetricsSuite);
return jsunity.done();