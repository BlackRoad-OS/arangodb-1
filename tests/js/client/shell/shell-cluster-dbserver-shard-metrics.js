/*jshint globalstrict:false, strict:false, maxlen: 500 */
/*global assertEqual, assertTrue, assertFalse, assertNotEqual, print */

// //////////////////////////////////////////////////////////////////////////////
// / DISCLAIMER
// /
// / Copyright 2014-2025 ArangoDB GmbH, Cologne, Germany
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
/// @author Jure Bajic
// //////////////////////////////////////////////////////////////////////////////

const jsunity = require("jsunity");
const db = require("@arangodb").db;
const internal = require("internal");
const { getMetric, getDBServers } = require("@arangodb/test-helper");

function ClusterDBServerShardMetricsTestSuite() {
  'use strict';
 
  const dbName = "UnitTestShardMetricsDatabase";
  const collectionName = "UnitTestShardMetricsCollection";

  const shardsNumMetric = "arangodb_shards_number";
  const shardsLeaderNumMetric = "arangodb_shards_leader_number";
  const shardsOutOfSyncNumMetric = "arangodb_shards_out_of_sync";
  const shardsNotReplicatedNumMetric = "arangodb_shards_not_replicated";

  // Helper function to get sum of a metric across all DB servers
  const getDBServerMetricSum = function(dbServers, metricName) {
    let sum = 0;
    for (let server of dbServers) {
      const value = getMetric(server.endpoint, metricName);
      sum += value;
    }
    return sum;
  };

  // Helper function to generate documents that cover all shards
  const generateDocsForAllShards = function(collection, numberOfShards, docsPerShard) {
    let shardMap = {};
    let docsToInsert = [];

    // Generate keys that cover all shards
    let i = 0;
    while (Object.keys(shardMap).length < numberOfShards || 
           Object.values(shardMap).some(count => count < docsPerShard)) {
      const key = `test${i}`;
      const shardId = collection.getResponsibleShard({ _key: key });
      
      if (!shardMap[shardId]) {
        shardMap[shardId] = 1;
      }
      
      if (shardMap[shardId] < docsPerShard) {
        shardMap[shardId]++;
        docsToInsert.push({ _key: key });
      }
      ++i;
    }

    return docsToInsert;
  };

  const getMetricsAndAssert = function(servers, expectedShardsNum, expectedShardsLeaderNum, expectedShardsOutOfSync, expectedShardsNotReplicated) {
    const shardsNumMetricValue = getDBServerMetricSum(servers, shardsNumMetric);
    const shardsLeaderNumMetricValue = getDBServerMetricSum(servers, shardsLeaderNumMetric);
    const shardsOutOfSyncNumMetricValue = getDBServerMetricSum(servers, shardsOutOfSyncNumMetric);
    const shardsNotReplicatedNumMetricValue = getDBServerMetricSum(servers, shardsNotReplicatedNumMetric);
    assertEqual(shardsNumMetricValue, expectedShardsNum);
    assertEqual(shardsLeaderNumMetricValue, expectedShardsLeaderNum);
    assertEqual(shardsOutOfSyncNumMetricValue, expectedShardsOutOfSync);
    assertEqual(shardsNotReplicatedNumMetricValue, expectedShardsNotReplicated);
  };

  return {
    tearDown: function () {
      db._useDatabase("_system");
      db._drop(collectionName);
      db._dropDatabase(dbName);
    },

    testShardCountMetricStability: function () {
      const dbServers = getDBServers();
      // 12 * 2, 12 shards
      getMetricsAndAssert(dbServers, 24, 12, 0, 0);

      db._createDatabase(dbName);
      internal.wait(3);
      // shardsNum:24 + 16 (2 * 8), shardsLeaderNum: 12 + 8 from new database
      getMetricsAndAssert(dbServers, 40, 20, 0, 0);

      db._useDatabase(dbName);
      db._create(collectionName, {
        numberOfShards: 6,
        replicationFactor: 2 // does not matter for the test
      });
      internal.wait(3);
 
      // Check stability of metrics
      let metricsMap = {
        [shardsNumMetric]: [],
        [shardsLeaderNumMetric]: [],
        [shardsOutOfSyncNumMetric]: [],
        [shardsNotReplicatedNumMetric]: [],
      };
      for(let i = 0; i < 40; i++) {
        Object.entries(metricsMap).forEach(([key, value]) => {
          value.push(getDBServerMetricSum(dbServers, key));
        });
      }

      // Assert the value of the first entry
      assertEqual(metricsMap[shardsNumMetric][0], 52); // 40 + 12 shards from new collection
      assertEqual(metricsMap[shardsLeaderNumMetric][0], 26); // 20 + 6 leaders from new collection
      assertEqual(metricsMap[shardsOutOfSyncNumMetric][0], 0);
      assertEqual(metricsMap[shardsNotReplicatedNumMetric][0], 0);

      // Test stability of metrics by asserting that all inserted values
      // of a metric are same as the first entry
      assertEqual(metricsMap[shardsNumMetric].length, 40);
      Object.entries(metricsMap).forEach(([key, value]) => {
        assertEqual(value[0], value[value.length - 1],
          `Metric ${key} is not stable`);
      });
    },

    testShardOutOfSyncMetricChange: function () {
      const dbServers = getDBServers();

      db._createDatabase(dbName);
      db._useDatabase(dbName);
      db._create(collectionName, {
        numberOfShards: 2,
        replicationFactor: 3,
      });

      // Assert initial state
      getMetricsAndAssert(dbServers, 46, 22, 0, 0);

      const shards = db[collectionName].shards(true);
      const dbServerWithLeaderId = Object.values(shards).map(servers => servers[0]);
      const dbServerWithoutLeader = dbServers.find(server => !dbServerWithLeaderId.includes(server.id));
      dbServerWithoutLeader.suspend();

      // Ensure we insert documents on ALL shards
      const docsToInsert = generateDocsForAllShards(db[collectionName], 2, 50);
      db[collectionName].insert(docsToInsert);

      // Get metrics after we kill one db server with follower
      const onlineServers = dbServers.filter(server => server.id !== dbServerWithoutLeader.id);
      getMetricsAndAssert(onlineServers, 44, 22, 2, 0);

      // Wait for maintenance to update metrics
      dbServerWithoutLeader.resume();
      internal.wait(2);

      // Eventually true
      for(let i = 0; i < 100; i++) {
        internal.wait(1);
        const shardsNumMetricValue = getDBServerMetricSum(dbServers, shardsNumMetric);
        if(shardsNumMetricValue !== 46) {
          print(`The metric ${shardsNumMetric} has value ${shardsNumMetricValue} should have been 46`);
          continue;
        }
        const shardsLeaderNumMetricValue = getDBServerMetricSum(dbServers, shardsLeaderNumMetric);
        if(shardsLeaderNumMetricValue !== 22) {
          print(`The metric ${shardsLeaderNumMetric} has value ${shardsLeaderNumMetricValue} should have been 22`);
          continue;
        }
        const shardsOutOfSyncNumMetricValue = getDBServerMetricSum(dbServers, shardsOutOfSyncNumMetric);
        if(shardsOutOfSyncNumMetricValue !== 0) {
          print(`The metric ${shardsOutOfSyncNumMetric} has value ${shardsOutOfSyncNumMetricValue} should have been 0`);
          continue;
        }
        const shardsNotReplicatedNumMetricValue = getDBServerMetricSum(dbServers, shardsNotReplicatedNumMetric);
        if(shardsNotReplicatedNumMetricValue !== 0) {
          print(`The metric ${shardsNotReplicatedNumMetric} has value ${shardsNotReplicatedNumMetricValue} should have been 0`);
          continue;
        }

        break;
      }

      getMetricsAndAssert(dbServers, 46, 22, 0, 0);
    },
      assertEqual(shardsOutOfSyncNumMetricValue, 0);
      assertEqual(shardsNotReplicatedNumMetricValue, 0);
    },
  };
}

jsunity.run(ClusterDBServerShardMetricsTestSuite);
return jsunity.done();

