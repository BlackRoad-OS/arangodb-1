/*jshint globalstrict:false, strict:false, maxlen: 500 */
/*global assertEqual, assertTrue, assertFalse, assertNotEqual, fail */

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

  return {
    tearDown: function () {
      db._useDatabase("_system");
      db._drop(collectionName);
      db._dropDatabase(dbName);
    },

    testShardCountMetricStability: function () {
      const dbServers = getDBServers();
      assertEqual(getDBServerMetricSum(dbServers, shardsNumMetric), 24); // 12 * 2
      assertEqual(getDBServerMetricSum(dbServers, shardsLeaderNumMetric), 12);
      assertEqual(getDBServerMetricSum(dbServers, shardsOutOfSyncNumMetric), 0);
      assertEqual(getDBServerMetricSum(dbServers, shardsNotReplicatedNumMetric), 0);

      db._createDatabase(dbName);
      internal.wait(3);
      assertEqual(getDBServerMetricSum(dbServers, shardsNumMetric), 40); // 24 + 16 (2 * 8) shards from new database
      assertEqual(getDBServerMetricSum(dbServers, shardsLeaderNumMetric), 20); // 12 + 8 from new database
      assertEqual(getDBServerMetricSum(dbServers, shardsOutOfSyncNumMetric), 0);
      assertEqual(getDBServerMetricSum(dbServers, shardsNotReplicatedNumMetric), 0);

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
      for(let i = 0; i < 20; i++) {
        Object.entries(metricsMap).forEach(([key, value]) => {
          value.push(getDBServerMetricSum(dbServers, key));
        });
      }

      // Test stability of metrics, they should not change
      assertEqual(metricsMap[shardsNumMetric].length, 20);
      Object.entries(metricsMap).forEach(([key, value]) => {
        print(`Metric ${key} has values: ${value.join(", ")}`);
        assertEqual(value[0], value[value.length - 1],
          `Metric ${key} is not stable`);
      });

      assertEqual(metricsMap[shardsNumMetric][0], 52); // 40 + 12 shards from new collection
      assertEqual(metricsMap[shardsLeaderNumMetric][0], 26); // 20 + 6 leaders from new collection
      assertEqual(metricsMap[shardsOutOfSyncNumMetric][0], 0);
      assertEqual(metricsMap[shardsNotReplicatedNumMetric][0], 0);
    },

    testShardOutOfSyncMetricChange: function () {
      const dbServers = getDBServers();

      db._createDatabase(dbName);
      db._useDatabase(dbName);
      db._create(collectionName, {
        numberOfShards: 2,
        replicationFactor: 3,
      });

      // Get shard information - shards(true) returns server IDs
      const shards = db[collectionName].shards(true);
      print(shards);
      const dbServerWithLeaderId = Object.values(shards).map(servers => servers[0]);
      print(dbServerWithLeaderId);
      const dbServerWithoutLeader = dbServers.find(server => !dbServerWithLeaderId.includes(server.id));
      print(`Killing dbServerWithoutLeader: ${dbServerWithoutLeader.id}`);
      dbServerWithoutLeader.suspend();

      // Ensure we insert documents on ALL shards
      const docsToInsert = generateDocsForAllShards(db[collectionName], 2, 50);
      db[collectionName].insert(docsToInsert);

      // Get metrics after collection creation to see if they change
      let shardsNumMetricValue = getDBServerMetricSum(dbServers.filter(server => server.id !== dbServerWithoutLeader.id), shardsNumMetric);
      let shardsLeaderNumMetricValue = getDBServerMetricSum(dbServers.filter(server => server.id !== dbServerWithoutLeader.id), shardsLeaderNumMetric);
      let shardsOutOfSyncNumMetricValue = getDBServerMetricSum(dbServers.filter(server => server.id !== dbServerWithoutLeader.id), shardsOutOfSyncNumMetric);
      let shardsNotReplicatedNumMetricValue = getDBServerMetricSum(dbServers.filter(server => server.id !== dbServerWithoutLeader.id), shardsNotReplicatedNumMetric);

      assertEqual(shardsNumMetricValue, 44);
      assertEqual(shardsLeaderNumMetricValue, 22);
      assertEqual(shardsOutOfSyncNumMetricValue, 2);
      assertEqual(shardsNotReplicatedNumMetricValue, 0);

      // Wait for maintenance to update metrics
      dbServerWithoutLeader.resume();
      internal.wait(2);

      // Eventually true
      const dbServerWithoutLeaderId = dbServerWithoutLeader.id;
      for(let i = 0; i < 100; i++) {
        internal.wait(1);
        shardsNumMetricValue = getDBServerMetricSum(dbServers.filter(server => server.id !== dbServerWithoutLeaderId), shardsNumMetric);
        print(`shardsNumMetricValue: ${shardsNumMetricValue}`);
        if(shardsNumMetricValue !== 44) {
          continue;
        }
        shardsLeaderNumMetricValue = getDBServerMetricSum(dbServers.filter(server => server.id !== dbServerWithoutLeaderId), shardsLeaderNumMetric);
        print(`shardsLeaderNumMetricValue: ${shardsLeaderNumMetricValue}`);
        if(shardsLeaderNumMetricValue !== 22) {
          continue;
        }
        shardsOutOfSyncNumMetricValue = getDBServerMetricSum(dbServers.filter(server => server.id !== dbServerWithoutLeaderId), shardsOutOfSyncNumMetric);
        print(`shardsOutOfSyncNumMetricValue: ${shardsOutOfSyncNumMetricValue}`);
        if(shardsOutOfSyncNumMetricValue !== 0) {
          continue;
        }
        shardsNotReplicatedNumMetricValue = getDBServerMetricSum(dbServers.filter(server => server.id !== dbServerWithoutLeaderId), shardsNotReplicatedNumMetric);
        print(`shardsNotReplicatedNumMetricValue: ${shardsNotReplicatedNumMetricValue}`);
        if(shardsNotReplicatedNumMetricValue !== 0) {
          continue;
        }

        break;
      }

      assertEqual(shardsNumMetricValue, 44);
      assertEqual(shardsLeaderNumMetricValue, 22);
      assertEqual(shardsOutOfSyncNumMetricValue, 0);
      assertEqual(shardsNotReplicatedNumMetricValue, 0);
    },
  };
}

jsunity.run(ClusterDBServerShardMetricsTestSuite);
return jsunity.done();

