/*jshint globalstrict:false, strict:false, sub: true, maxlen: 500 */
/*global assertEqual, assertTrue, assertFalse, AQL_EXPLAIN */

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
/// @author Copyright 2025, ArangoDB GmbH, Cologne, Germany
// //////////////////////////////////////////////////////////////////////////////

const jsunity = require("jsunity");
const db = require("@arangodb").db;
const gm = require("@arangodb/general-graph");
const th = require("@arangodb/test-helper");

const graphName = "UnitTestGraph";
const vName = "UnitTestVertices";
const eName = "UnitTestEdges";

const optimizerRuleName = "short-traversal-to-join";

const tearDownAll = () => {
  try {
    gm._drop(graphName, true);
  } catch (e) {
    // Don't care for error, we might runinitially with no graph exist
  }
  db._drop(eName);
  db._drop(vName);
};

const createGraph = () => {
  gm._create(graphName, [gm._relation(eName, vName, vName)
  ], [], {});

  const vertices = [];
  const edges = [];

  for (var i = 0; i < 19; i++) {
    vertices.push({
      _key: i.toString(),
      colour: "green"
    });
  }
  for (var j = 19; j < 29; j++) {
    vertices.push({
      _key: j.toString(),
      colour: "red"
    });
  }

  edges.push({ _from: `${vName}/0`, _to: `${vName}/1`, weight: 0, colour: "green" });
  edges.push({ _from: `${vName}/1`, _to: `${vName}/2`, weight: 1, colour: "green" });
  edges.push({ _from: `${vName}/2`, _to: `${vName}/3`, weight: 0, colour: "green" });

  edges.push({ _from: `${vName}/4`, _to: `${vName}/5`, weight: 0.5, colour: "red" });
  edges.push({ _from: `${vName}/5`, _to: `${vName}/6`, weight: 0, colour: "red" });
  edges.push({ _from: `${vName}/6`, _to: `${vName}/7`, weight: 2.5, colour: "red" });

  edges.push({ _from: `${vName}/8`, _to: `${vName}/9`, weight: 0.5, colour: "red"});
  edges.push({ _from: `${vName}/9`, _to: `${vName}/10`, weight: 0, colour: "green"});
  edges.push({ _from: `${vName}/10`, _to: `${vName}/11`, weight: 2.5, colour: "red"});
  edges.push({ _from: `${vName}/11`, _to: `${vName}/12`, weight: 0, colour: "green"});
  edges.push({ _from: `${vName}/12`, _to: `${vName}/13`, weight: 1.0, colour: "purple"});
  edges.push({ _from: `${vName}/13`, _to: `${vName}/14`, weight: 2, colour: "banana"});

  edges.push({ _from: `${vName}/9`, _to: `${vName}/15`, weight: 0, colour: "green"});
  edges.push({ _from: `${vName}/15`, _to: `${vName}/16`, weight: 1, colour: "green"});
  edges.push({ _from: `${vName}/16`, _to: `${vName}/11`, weight: 1, colour: "green"});

  edges.push({ _from: `${vName}/9`, _to: `${vName}/17`, weight: 0, colour: "purple"});
  edges.push({ _from: `${vName}/17`, _to: `${vName}/18`, weight: 0, colour: "purple"});
  edges.push({ _from: `${vName}/18`, _to: `${vName}/14`, weight: 1, colour: "purple"});


  /* there is a path of length 5 with green edges and a path of length 4 with purple
     the test below ascertains that the path with purple edges is actually skipped
     and the path with green edges is found if there is a filter on edges only
     letting green edges pass. */
  edges.push({ _from: `${vName}/19`, _to: `${vName}/20`, weight: 1, colour: "green" });
  edges.push({ _from: `${vName}/20`, _to: `${vName}/21`, weight: 1, colour: "green" });
  edges.push({ _from: `${vName}/21`, _to: `${vName}/22`, weight: 1, colour: "green" });
  edges.push({ _from: `${vName}/22`, _to: `${vName}/23`, weight: 1, colour: "green" });

  edges.push({ _from: `${vName}/19`, _to: `${vName}/20`, weight: 1, colour: "purple" });
  edges.push({ _from: `${vName}/20`, _to: `${vName}/21`, weight: 1, colour: "purple" });
  edges.push({ _from: `${vName}/21`, _to: `${vName}/23`, weight: 1, colour: "purple" });



  db[vName].save(vertices);
  db[eName].save(edges);
};

function assertRuleFires(query) {
  const result = th.AQL_EXPLAIN(query);
  assertTrue(result.plan.rules.includes(optimizerRuleName),
             `[${result.plan.rules}] does not contain "${optimizerRuleName}"`);
}

function assertRuleDoesNotFire(query) {
  const result = th.AQL_EXPLAIN(query);
  assertFalse(result.plan.rules.includes(optimizerRuleName),
             `[${result.plan.rules}] contains "${optimizerRuleName}"`);
}

function getVerticesAndEdgesFromPath(path) {
  return {
    vertices: path.vertices.map((v) => v._id),
    edges: path.edges.map((e) => [e._from, e._to])
  };
}

function assertSameResults(query) {
  const resultWith = db._query(query).toArray();
  const resultWithPaths = resultWith.map(getVerticesAndEdgesFromPath);

  const resultWithout = db._query(query, {}, {optimizer: {rules: [`-${optimizerRuleName}`]}}).toArray();
  const resultWithoutPaths = resultWithout.map(getVerticesAndEdgesFromPath);

  assertEqual(resultWithPaths, resultWithoutPaths);
}

function enumeratePathsFilter() {
  var testObj = {
    setUpAll: function () {
      tearDownAll();
      createGraph();
    },
    tearDownAll,

    testRuleFires: function() {
      const query = `FOR v,e,p IN 1..1 OUTBOUND "${vName}/0" GRAPH ${graphName}
                       RETURN p`;
      assertRuleFires(query);
      assertSameResults(query);
    },

    testRuleDoesNotFire: function() {
      const query = `FOR v,e,p IN 1..2 OUTBOUND "${vName}/0" GRAPH ${graphName}
                       RETURN p`;
      assertRuleDoesNotFire(query);
    }

  };

  return testObj;
}

jsunity.run(enumeratePathsFilter);
return jsunity.done();
