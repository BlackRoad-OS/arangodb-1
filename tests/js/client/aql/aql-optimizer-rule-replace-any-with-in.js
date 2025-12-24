/*jshint globalstrict:false, strict:false, maxlen: 500 */
/*global assertEqual, assertTrue, fail */

// //////////////////////////////////////////////////////////////////////////////
// / DISCLAIMER
// /
// / Copyright 2014-2025 Arango GmbH, Cologne, Germany
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
/// @author Julia Puget
/// @author Copyright 2014, triAGENS GmbH, Cologne, Germany
// //////////////////////////////////////////////////////////////////////////////

var internal = require("internal");
var jsunity = require("jsunity");
var helper = require("@arangodb/aql-helper");
var getQueryResults = helper.getQueryResults;
var findExecutionNodes = helper.findExecutionNodes;
const db = require('internal').db;
let {instanceRole} = require('@arangodb/testutils/instance');
let IM = global.instanceManager;

function NewAqlReplaceAnyWithINTestSuite() {
    var replace;
    var ruleName = "replace-any-eq-with-in";

    var getPlan = function (query, params, options) {
        return db._createStatement({query: query, bindVars: params, options: options}).explain().plan;
    };

    var ruleIsNotUsed = function (query, params) {
        var plan = getPlan(query, params, {optimizer: {rules: ["-all", "+" + ruleName]}});
        assertTrue(plan.rules.indexOf(ruleName) === -1, "Rule should not be used: " + query);
    };

    var executeWithRule = function (query, params) {
        return db._query(query, params, {optimizer: {rules: ["-all", "+" + ruleName]}}).toArray();
    };

    var executeWithoutRule = function (query, params) {
        return db._query(query, params, {optimizer: {rules: ["-all"]}}).toArray();
    };

    var executeWithOrRule = function (query, params) {
        return db._query(query, params, {optimizer: {rules: ["-all", "+replace-or-with-in"]}}).toArray();
    };

    var verifyExecutionPlan = function (query, params) {
        var explainWithRule = db._createStatement({
            query: query,
            bindVars: params || {},
            options: {optimizer: {rules: ["-all", "+" + ruleName]}}
        }).explain();

        var explainWithoutRule = db._createStatement({
            query: query,
            bindVars: params || {},
            options: {optimizer: {rules: ["-all"]}}
        }).explain();

        var planWithRule = explainWithRule.plan;
        var planWithoutRule = explainWithoutRule.plan;

        assertTrue(planWithRule.rules.indexOf(ruleName) !== -1,
            "Plan with rule enabled should contain rule '" + ruleName + "': " + query);
        assertTrue(planWithoutRule.rules.indexOf(ruleName) === -1,
            "Plan without rule should NOT contain rule '" + ruleName + "': " + query);

        var filterNodesWith = findExecutionNodes(planWithRule, "FilterNode");
        var filterNodesWithout = findExecutionNodes(planWithoutRule, "FilterNode");
        var calcNodesWith = findExecutionNodes(planWithRule, "CalculationNode");
        var calcNodesWithout = findExecutionNodes(planWithoutRule, "CalculationNode");

        assertTrue(filterNodesWith.length > 0 && filterNodesWithout.length > 0,
            "Plans should have FilterNodes: " + query);
        assertTrue(calcNodesWith.length > 0 && calcNodesWithout.length > 0,
            "Plans should have CalculationNodes: " + query);

        assertTrue(planWithRule.nodes.length > 0, "Plan with rule should have nodes: " + query);
        assertTrue(planWithoutRule.nodes.length > 0, "Plan without rule should have nodes: " + query);

        return {withRule: planWithRule, withoutRule: planWithoutRule};
    };

    var verifyPlansDifferent = function (planWithRule, planWithoutRule, query) {
        assertTrue(planWithRule.rules.indexOf(ruleName) !== -1,
            "Plan with rule enabled should contain the rule: " + query);
        assertTrue(planWithoutRule.rules.indexOf(ruleName) === -1,
            "Plan without rule should not contain the rule: " + query);

        var calcNodesWith = findExecutionNodes(planWithRule, "CalculationNode");
        var calcNodesWithout = findExecutionNodes(planWithoutRule, "CalculationNode");

        assertTrue(calcNodesWith.length > 0 || calcNodesWithout.length > 0,
            "Plans should have calculation nodes: " + query);

        assertTrue(planWithRule.nodes.length > 0, "Plan with rule should have nodes");
        assertTrue(planWithoutRule.nodes.length > 0, "Plan without rule should have nodes");
    };

    return {

        setUpAll: function () {
            IM.debugClearFailAt();
            internal.db._drop("UnitTestsNewAqlReplaceAnyWithINTestSuite");
            replace = internal.db._create("UnitTestsNewAqlReplaceAnyWithINTestSuite");

            let docs = [];
            for (var i = 1; i <= 10; ++i) {
                docs.push({"value": i, "name": "Alice", "tags": ["a", "b"], "categories": ["x", "y"]});
                docs.push({"value": i + 10, "name": "Bob", "tags": ["b", "c"], "categories": ["y", "z"]});
                docs.push({"value": i + 20, "name": "Carol", "tags": ["c", "d"], "categories": ["z"]});
                docs.push({"a": {"b": i}});
            }
            replace.insert(docs);

            replace.ensureIndex({type: "persistent", fields: ["name"]});
            replace.ensureIndex({type: "persistent", fields: ["a.b"]});
        },

        tearDownAll: function () {
            IM.debugClearFailAt();
            internal.db._drop("UnitTestsNewAqlReplaceAnyWithINTestSuite");
            replace = null;
        },

        setUp: function () {
            IM.debugClearFailAt();
        },

        tearDown: function () {
            IM.debugClearFailAt();
        },

        testOom: function () {
            if (!IM.debugCanUseFailAt()) {
                return;
            }
            IM.debugSetFailAt("OptimizerRules::replaceAnyEqWithInRuleOom");
            try {
                db._query("FOR x IN " + replace.name() + " FILTER ['Alice', 'Bob'] ANY == x.name RETURN x");
                fail();
            } catch (err) {
                assertEqual(internal.errors.ERROR_DEBUG.code, err.errorNum);
            }
        },

        testExecutionPlanVerification: function () {
            var query = "FOR x IN " + replace.name() +
                " FILTER ['Alice', 'Bob'] ANY == x.name SORT x.value RETURN x.value";

            verifyExecutionPlan(query, {});
        },

        testFiresBasic: function () {
            var query = "FOR x IN " + replace.name() +
                " FILTER ['Alice', 'Bob'] ANY == x.name SORT x.value RETURN x.value";

            var plans = verifyExecutionPlan(query, {});
            verifyPlansDifferent(plans.withRule, plans.withoutRule, query);

            var expected = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20];
            var actual = getQueryResults(query);
            assertEqual(expected, actual);

            var withRule = executeWithRule(query, {});
            var withoutRule = executeWithoutRule(query, {});
            assertEqual(withRule, withoutRule, "Results with and without rule should match");

            var orQuery = "FOR x IN " + replace.name() +
                " FILTER x.name == 'Alice' || x.name == 'Bob' SORT x.value RETURN x.value";
            var orResult = executeWithOrRule(orQuery, {});
            assertEqual(withRule, orResult, "Results with ANY == should match OR query");
        },

        testFiresSingleValue: function () {
            var query = "FOR x IN " + replace.name() +
                " FILTER ['Alice'] ANY == x.name SORT x.value RETURN x.value";

            var plans = verifyExecutionPlan(query, {});
            verifyPlansDifferent(plans.withRule, plans.withoutRule, query);

            var expected = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
            var actual = getQueryResults(query);
            assertEqual(expected, actual);

            var withRule = executeWithRule(query, {});
            var withoutRule = executeWithoutRule(query, {});
            assertEqual(withRule, withoutRule, "Results with and without rule should match");

            var orQuery = "FOR x IN " + replace.name() +
                " FILTER x.name == 'Alice' SORT x.value RETURN x.value";
            var orResult = executeWithOrRule(orQuery, {});
            assertEqual(withRule, orResult, "Results with ANY == should match OR query");
        },

        testFiresEmptyArray: function () {
            var query = "FOR x IN " + replace.name() +
                " FILTER [] ANY == x.name RETURN x.value";

            var plans = verifyExecutionPlan(query, {});
            verifyPlansDifferent(plans.withRule, plans.withoutRule, query);

            var expected = [];
            var actual = getQueryResults(query);
            assertEqual(expected, actual);

            var withRule = executeWithRule(query, {});
            var withoutRule = executeWithoutRule(query, {});
            assertEqual(withRule, withoutRule, "Results with and without rule should match");

            var inQuery = "FOR x IN " + replace.name() +
                " FILTER x.name IN [] RETURN x.value";
            var inResult = executeWithOrRule(inQuery, {});
            assertEqual(withRule, inResult, "Results with ANY == should match IN query");
        },

        testFiresManyValues: function () {
            var query = "FOR x IN " + replace.name() +
                " FILTER ['Alice', 'Bob', 'Carol', 'David', " +
                "         'Eve', 'Frank', 'Grace', 'Henry'] " +
                " ANY == x.name SORT x.value RETURN x.value";

            var plans = verifyExecutionPlan(query, {});
            verifyPlansDifferent(plans.withRule, plans.withoutRule, query);

            var expected = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
                            16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30];
            var actual = getQueryResults(query);
            assertEqual(expected, actual);

            var withRule = executeWithRule(query, {});
            var withoutRule = executeWithoutRule(query, {});
            assertEqual(withRule, withoutRule, "Results with and without rule should match");

            var orQuery = "FOR x IN " + replace.name() +
                " FILTER x.name == 'Alice' || x.name == 'Bob' || x.name == 'Carol' || x.name == 'David' ||" +
                "        x.name == 'Eve' || x.name == 'Frank' || x.name == 'Grace' || x.name == 'Henry' " +
                " SORT x.value RETURN x.value";
            var orResult = executeWithOrRule(orQuery, {});
            assertEqual(withRule, orResult, "Results with ANY == should match OR query");
        },

        testFiresNestedAttribute: function () {
            var query = "FOR x IN " + replace.name() +
                " FILTER [1, 2] ANY == x.a.b SORT x.a.b RETURN x.a.b";

            var plans = verifyExecutionPlan(query, {});
            verifyPlansDifferent(plans.withRule, plans.withoutRule, query);

            var expected = [1, 2];
            var actual = getQueryResults(query);
            assertEqual(expected, actual);

            var withRule = executeWithRule(query, {});
            var withoutRule = executeWithoutRule(query, {});
            assertEqual(withRule, withoutRule, "Results with and without rule should match");

            var orQuery = "FOR x IN " + replace.name() +
                " FILTER x.a.b == 1 || x.a.b == 2 SORT x.a.b RETURN x.a.b";
            var orResult = executeWithOrRule(orQuery, {});
            assertEqual(withRule, orResult, "Results with ANY == should match OR query");
        },

        testFiresBind: function () {
            var query =
                "FOR v IN " + replace.name()
                + " FILTER @names ANY == v.name SORT v.value RETURN v.value";
            var params = {"names": ["Alice", "Bob"]};

            var plans = verifyExecutionPlan(query, params);
            verifyPlansDifferent(plans.withRule, plans.withoutRule, query);

            var expected = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20];
            var actual = getQueryResults(query, params);
            assertEqual(expected, actual);

            var withRule = executeWithRule(query, params);
            var withoutRule = executeWithoutRule(query, params);
            assertEqual(withRule, withoutRule, "Results with and without rule should match");

            var orQuery = "FOR v IN " + replace.name()
                + " FILTER v.name == 'Alice' || v.name == 'Bob' SORT v.value RETURN v.value";
            var orResult = executeWithOrRule(orQuery, {});
            assertEqual(withRule, orResult, "Results with ANY == should match OR query");
        },

        testFiresVariables: function () {
            var query =
                "LET names = ['Alice', 'Bob'] FOR v IN " + replace.name()
                + " FILTER names ANY == v.name SORT v.value RETURN v.value";

            var plans = verifyExecutionPlan(query, {});
            verifyPlansDifferent(plans.withRule, plans.withoutRule, query);

            var expected = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20];
            var actual = getQueryResults(query, {});
            assertEqual(expected, actual);

            var withRule = executeWithRule(query, {});
            var withoutRule = executeWithoutRule(query, {});
            assertEqual(withRule, withoutRule, "Results with and without rule should match");

            var orQuery = "LET names = ['Alice', 'Bob'] FOR v IN " + replace.name()
                + " FILTER v.name == 'Alice' || v.name == 'Bob' SORT v.value RETURN v.value";
            var orResult = executeWithOrRule(orQuery, {});
            assertEqual(withRule, orResult, "Results with ANY == should match OR query");
        },

        testFiresMultipleAnyEq: function () {
            var query =
                "FOR v IN " + replace.name()
                + " FILTER ['Alice', 'Bob'] ANY == v.name && v.value <= 20 SORT v.value RETURN v.value";

            var plans = verifyExecutionPlan(query, {});
            verifyPlansDifferent(plans.withRule, plans.withoutRule, query);

            var expected = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20];
            var actual = getQueryResults(query, {});
            assertEqual(expected, actual);

            var withRule = executeWithRule(query, {});
            var withoutRule = executeWithoutRule(query, {});
            assertEqual(withRule, withoutRule, "Results with and without rule should match");

            var orQuery = "FOR v IN " + replace.name()
                + " FILTER (v.name == 'Alice' || v.name == 'Bob') && v.value <= 20 SORT v.value RETURN v.value";
            var orResult = executeWithOrRule(orQuery, {});
            assertEqual(withRule, orResult, "Results with ANY == should match OR query");
        },

        testFiresMultipleAnyEqDifferentAttributes: function () {
            var query =
                "FOR v IN " + replace.name()
                + " FILTER ['Alice'] ANY == v.name && v.value <= 10 SORT v.value RETURN v.value";

            var plans = verifyExecutionPlan(query, {});
            verifyPlansDifferent(plans.withRule, plans.withoutRule, query);

            var expected = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
            var actual = getQueryResults(query, {});
            assertEqual(expected, actual);

            var withRule = executeWithRule(query, {});
            var withoutRule = executeWithoutRule(query, {});
            assertEqual(withRule, withoutRule, "Results with and without rule should match");

            var orQuery = "FOR v IN " + replace.name()
                + " FILTER v.name == 'Alice' && v.value <= 10 SORT v.value RETURN v.value";
            var orResult = executeWithOrRule(orQuery, {});
            assertEqual(withRule, orResult, "Results with ANY == should match OR query");
        },

        testFiresNoCollection: function () {
            var query =
                "FOR x in 1..10 LET doc = {name: 'Alice', value: x} FILTER ['Alice', 'Bob'] " +
                "ANY == doc.name SORT doc.value RETURN doc.value";

            var plans = verifyExecutionPlan(query, {});
            verifyPlansDifferent(plans.withRule, plans.withoutRule, query);

            var expected = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
            var actual = getQueryResults(query);
            assertEqual(expected, actual);

            var withRule = executeWithRule(query, {});
            var withoutRule = executeWithoutRule(query, {});
            assertEqual(withRule, withoutRule, "Results with and without rule should match");
        },

        testFiresNestedInSubquery: function () {
            var query =
                "FOR outer IN " + replace.name() +
                " LET sub = (FOR inner IN " + replace.name() +
                " FILTER ['Alice'] ANY == inner.name RETURN inner.value)" +
                " FILTER ['Alice'] ANY == outer.name RETURN outer.value";

            var plans = verifyExecutionPlan(query, {});
            verifyPlansDifferent(plans.withRule, plans.withoutRule, query);

            var expected = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
            var actual = getQueryResults(query, {});
            assertEqual(expected, actual);

            var withRule = executeWithRule(query, {});
            var withoutRule = executeWithoutRule(query, {});
            assertEqual(withRule, withoutRule, "Results with and without rule should match");
        },

        testDudNotAnyQuantifier: function () {
            var query =
                "FOR x IN " + replace.name() +
                " FILTER ['Alice', 'Bob'] ALL == x.name RETURN x.value";

            ruleIsNotUsed(query, {});
        },

        testDudNoArray: function () {
            var query =
                "FOR x IN " + replace.name() +
                " FILTER 'Alice' ANY == x.name RETURN x.value";

            ruleIsNotUsed(query, {});
        },

        testDudNonDeterministicArray: function () {
            var query =
                "FOR x IN " + replace.name() +
                " FILTER NOOPT(['Alice', 'Bob']) ANY == x.name RETURN x.value";

            ruleIsNotUsed(query, {});
        },

        testDudNoAttribute: function () {
            var query =
                "FOR x IN " + replace.name() +
                " FILTER ['Alice', 'Bob'] ANY == 'Alice' RETURN x.value";

            ruleIsNotUsed(query, {});
        },

        testDudBothArrays: function () {
            var query =
                "FOR x IN " + replace.name() +
                " FILTER ['Alice'] ANY == ['Bob'] RETURN x.value";

            ruleIsNotUsed(query, {});
        },

        testDudDifferentOperators: function () {
            var query =
                "FOR x IN " + replace.name() +
                " FILTER ['Alice', 'Bob'] ANY != x.name RETURN x.value";

            ruleIsNotUsed(query, {});
        },

        testIndexOptimizationWithNameIndex: function () {
            var query =
                "FOR x IN " + replace.name() +
                " FILTER ['Alice', 'Bob'] ANY == x.name SORT x.value RETURN x.value";

            var explainWithRule = db._createStatement({
                query: query,
                bindVars: {},
                options: {optimizer: {rules: ["-all", "+replace-any-eq-with-in", "+use-indexes"]}}
            }).explain();

            var explainWithoutRule = db._createStatement({
                query: query,
                bindVars: {},
                options: {optimizer: {rules: ["-all", "+use-indexes"]}}
            }).explain();

            var planWithRule = explainWithRule.plan;
            var planWithoutRule = explainWithoutRule.plan;

            assertTrue(planWithRule.rules.indexOf(ruleName) !== -1,
                "Plan with rule should contain replace-any-eq-with-in");
            assertTrue(planWithRule.rules.indexOf("use-indexes") !== -1,
                "Plan with rule should contain use-indexes");

            var indexNodesWith = findExecutionNodes(planWithRule, "IndexNode");
            var enumNodesWith = findExecutionNodes(planWithRule, "EnumerateCollectionNode");
            var indexNodesWithout = findExecutionNodes(planWithoutRule, "IndexNode");
            var enumNodesWithout = findExecutionNodes(planWithoutRule, "EnumerateCollectionNode");

            assertTrue(indexNodesWith.length > 0,
                "Plan with replace-any-eq-with-in should use IndexNode. " +
                "Rules: " + JSON.stringify(planWithRule.rules));
            assertTrue(enumNodesWith.length === 0,
                "Plan with replace-any-eq-with-in should NOT use EnumerateCollectionNode");

            if (indexNodesWithout.length === 0) {
                assertTrue(enumNodesWithout.length > 0,
                    "Plan without replace-any-eq-with-in should use EnumerateCollectionNode");
            }

            var expected = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20];
            var withRule = executeWithRule(query, {});
            var withoutRule = executeWithoutRule(query, {});

            assertEqual(expected, withRule);
            assertEqual(withRule, withoutRule, "Results should match");
        },

        testIndexOptimizationWithNestedAttributeIndex: function () {
            var query =
                "FOR x IN " + replace.name() +
                " FILTER [1, 2] ANY == x.a.b SORT x.a.b RETURN x.a.b";

            var explainWithRule = db._createStatement({
                query: query,
                bindVars: {},
                options: {optimizer: {rules: ["-all", "+replace-any-eq-with-in", "+use-indexes"]}}
            }).explain();

            var planWithRule = explainWithRule.plan;

            assertTrue(planWithRule.rules.indexOf(ruleName) !== -1,
                "Plan with rule should contain replace-any-eq-with-in");
            assertTrue(planWithRule.rules.indexOf("use-indexes") !== -1,
                "Plan with rule should contain use-indexes");

            var indexNodesWith = findExecutionNodes(planWithRule, "IndexNode");
            var enumNodesWith = findExecutionNodes(planWithRule, "EnumerateCollectionNode");

            assertTrue(indexNodesWith.length > 0,
                "Plan with replace-any-eq-with-in should use IndexNode for nested attribute");
            assertTrue(enumNodesWith.length === 0,
                "Plan with replace-any-eq-with-in should NOT use EnumerateCollectionNode");

            var expected = [1, 2];
            var withRule = executeWithRule(query, {});
            var withoutRule = executeWithoutRule(query, {});

            assertEqual(expected, withRule);
            assertEqual(withRule, withoutRule, "Results should match");
        },

        testIndexOptimizationMultipleConditions: function () {
            var query =
                "FOR x IN " + replace.name() +
                " FILTER ['Alice'] ANY == x.name && x.value <= 10 SORT x.value RETURN x.value";

            var explainWithRule = db._createStatement({
                query: query,
                bindVars: {},
                options: {optimizer: {rules: ["-all", "+replace-any-eq-with-in", "+use-indexes"]}}
            }).explain();

            var planWithRule = explainWithRule.plan;

            assertTrue(planWithRule.rules.indexOf(ruleName) !== -1,
                "Plan with rule should contain replace-any-eq-with-in");
            assertTrue(planWithRule.rules.indexOf("use-indexes") !== -1,
                "Plan with rule should contain use-indexes");

            var indexNodesWith = findExecutionNodes(planWithRule, "IndexNode");

            assertTrue(indexNodesWith.length > 0,
                "Plan with replace-any-eq-with-in should use IndexNode even with multiple conditions");

            var expected = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
            var withRule = executeWithRule(query, {});
            var withoutRule = executeWithoutRule(query, {});

            assertEqual(expected, withRule);
            assertEqual(withRule, withoutRule, "Results should match");
        },

        testFiresDuplicateValues: function () {
            var query = "FOR x IN " + replace.name() +
                " FILTER ['Alice', 'Alice', 'Bob', 'Bob', 'Alice'] ANY == x.name SORT x.value RETURN x.value";

            var plans = verifyExecutionPlan(query, {});
            verifyPlansDifferent(plans.withRule, plans.withoutRule, query);

            var expected = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20];
            var actual = getQueryResults(query);
            assertEqual(expected, actual);

            var withRule = executeWithRule(query, {});
            var withoutRule = executeWithoutRule(query, {});
            assertEqual(withRule, withoutRule, "Results with and without rule should match");

            var inQuery = "FOR x IN " + replace.name() +
                " FILTER x.name IN ['Alice', 'Alice', 'Bob', 'Bob', 'Alice'] SORT x.value RETURN x.value";
            var inResult = executeWithOrRule(inQuery, {});
            assertEqual(withRule, inResult, "Results with ANY == should match IN query");
        },

        testFiresEmptyString: function () {
            var query = "FOR x IN " + replace.name() +
                " FILTER ['', 'Alice'] ANY == x.name SORT x.value RETURN x.value";

            var plans = verifyExecutionPlan(query, {});
            verifyPlansDifferent(plans.withRule, plans.withoutRule, query);

            var expected = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
            var actual = getQueryResults(query);
            assertEqual(expected, actual);

            var withRule = executeWithRule(query, {});
            var withoutRule = executeWithoutRule(query, {});
            assertEqual(withRule, withoutRule, "Results with and without rule should match");

            var inQuery = "FOR x IN " + replace.name() +
                " FILTER x.name IN ['', 'Alice'] SORT x.value RETURN x.value";
            var inResult = executeWithOrRule(inQuery, {});
            assertEqual(withRule, inResult, "Results with ANY == should match IN query");
        },

        testFiresSpecialCharacters: function () {
            var query = "FOR x IN " + replace.name() +
                " FILTER ['Alice', 'O\\'Brien', 'test\"quote', 'new\\nline'] ANY == x.name SORT x.value RETURN x.value";

            var plans = verifyExecutionPlan(query, {});
            verifyPlansDifferent(plans.withRule, plans.withoutRule, query);

            var actual = getQueryResults(query);
            var withRule = executeWithRule(query, {});
            var withoutRule = executeWithoutRule(query, {});
            assertEqual(withRule, withoutRule, "Results with and without rule should match");

            var inQuery = "FOR x IN " + replace.name() +
                " FILTER x.name IN ['Alice', 'O\\'Brien', 'test\"quote', 'new\\nline'] SORT x.value RETURN x.value";
            var inResult = executeWithOrRule(inQuery, {});
            assertEqual(withRule, inResult, "Results with ANY == should match IN query");
        },

        testFiresIndexedAccess: function () {
            var query = "FOR x IN " + replace.name() +
                " FILTER ['Alice', 'Bob'] ANY == x['name'] SORT x.value RETURN x.value";

            var plans = verifyExecutionPlan(query, {});
            verifyPlansDifferent(plans.withRule, plans.withoutRule, query);

            var expected = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20];
            var actual = getQueryResults(query);
            assertEqual(expected, actual);

            var withRule = executeWithRule(query, {});
            var withoutRule = executeWithoutRule(query, {});
            assertEqual(withRule, withoutRule, "Results with and without rule should match");

            var inQuery = "FOR x IN " + replace.name() +
                " FILTER x['name'] IN ['Alice', 'Bob'] SORT x.value RETURN x.value";
            var inResult = executeWithOrRule(inQuery, {});
            assertEqual(withRule, inResult, "Results with ANY == should match IN query");
        },

        testFiresEmptyArrayOptimization: function () {
            var query = "FOR x IN " + replace.name() +
                " FILTER [] ANY == x.name RETURN x.value";

            var explainWithRule = db._createStatement({
                query: query,
                bindVars: {},
                options: {optimizer: {rules: ["-all", "+replace-any-eq-with-in"]}}
            }).explain();

            var planWithRule = explainWithRule.plan;
            var noResultNodes = findExecutionNodes(planWithRule, "NoResultsNode");

            assertTrue(planWithRule.rules.indexOf(ruleName) !== -1,
                "Plan with rule should contain replace-any-eq-with-in");

            var expected = [];
            var withRule = executeWithRule(query, {});
            var withoutRule = executeWithoutRule(query, {});

            assertEqual(expected, withRule);
            assertEqual(withRule, withoutRule, "Results with and without rule should match");

            var inQuery = "FOR x IN " + replace.name() +
                " FILTER x.name IN [] RETURN x.value";
            var inResult = executeWithOrRule(inQuery, {});
            assertEqual(withRule, inResult, "Results with ANY == should match IN query");
        },

        testSingleValueOptimization: function () {
            var query = "FOR x IN " + replace.name() +
                " FILTER ['Alice'] ANY == x.name SORT x.value RETURN x.value";

            var explainWithRule = db._createStatement({
                query: query,
                bindVars: {},
                options: {optimizer: {rules: ["-all", "+replace-any-eq-with-in"]}}
            }).explain();

            var planWithRule = explainWithRule.plan;

            assertTrue(planWithRule.rules.indexOf(ruleName) !== -1,
                "Plan with rule should contain replace-any-eq-with-in");

            var expected = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
            var withRule = executeWithRule(query, {});
            var withoutRule = executeWithoutRule(query, {});

            assertEqual(expected, withRule);
            assertEqual(withRule, withoutRule, "Results with and without rule should match");

            var eqQuery = "FOR x IN " + replace.name() +
                " FILTER x.name == 'Alice' SORT x.value RETURN x.value";
            var eqResult = db._query(eqQuery).toArray();
            assertEqual(withRule, eqResult, "Single-value ANY == should match == query");
        },

        testChainedOptimizations: function () {
            var query = "FOR x IN " + replace.name() +
                " FILTER ['Alice', 'Alice', 'Bob'] ANY == x.name " +
                "   AND x.value > 5 " +
                "   AND x.value < 15 " +
                "SORT x.value RETURN x.value";

            var explainWithAllRules = db._createStatement({
                query: query,
                bindVars: {},
                options: {optimizer: {rules: ["-all", "+replace-any-eq-with-in", "+use-indexes"]}}
            }).explain();

            var planWithAllRules = explainWithAllRules.plan;

            assertTrue(planWithAllRules.rules.indexOf(ruleName) !== -1,
                "Plan should contain replace-any-eq-with-in");
            assertTrue(planWithAllRules.rules.indexOf("use-indexes") !== -1,
                "Plan should contain use-indexes");

            var indexNodes = findExecutionNodes(planWithAllRules, "IndexNode");
            assertTrue(indexNodes.length > 0,
                "Should use index after ANY == transformation");

            var expected = [6, 7, 8, 9, 10, 11, 12, 13, 14];
            var withRule = executeWithRule(query, {});
            var withoutRule = executeWithoutRule(query, {});

            assertEqual(expected, withRule);
            assertEqual(withRule, withoutRule, "Results with and without rule should match");
        },

        testResultsMatchBetweenAnyAndIn: function () {
            var testCases = [
                {
                    any: "['Alice'] ANY == x.name",
                    in: "x.name IN ['Alice']"
                },
                {
                    any: "['Alice', 'Bob', 'Carol'] ANY == x.name",
                    in: "x.name IN ['Alice', 'Bob', 'Carol']"
                },
                {
                    any: "[1, 2] ANY == x.a.b",
                    in: "x.a.b IN [1, 2]"
                },
                {
                    any: "[] ANY == x.name",
                    in: "x.name IN []"
                }
            ];

            testCases.forEach(function(testCase) {
                var anyQuery = "FOR x IN " + replace.name() +
                    " FILTER " + testCase.any + " SORT x.value RETURN x.value";
                var inQuery = "FOR x IN " + replace.name() +
                    " FILTER " + testCase.in + " SORT x.value RETURN x.value";

                var anyResult = db._query(anyQuery, {}, 
                    {optimizer: {rules: ["-all", "+replace-any-eq-with-in"]}}).toArray();
                var inResult = db._query(inQuery, {}, 
                    {optimizer: {rules: ["-all"]}}).toArray();

                assertEqual(anyResult, inResult,
                    "ANY == and IN should produce same results for: " + testCase.any);
            });
        },

        testIndexUsageComparison: function () {
            var anyQuery = "FOR x IN " + replace.name() +
                " FILTER ['Alice', 'Bob'] ANY == x.name RETURN x";
            var inQuery = "FOR x IN " + replace.name() +
                " FILTER x.name IN ['Alice', 'Bob'] RETURN x";

            var anyPlan = db._createStatement({
                query: anyQuery,
                bindVars: {},
                options: {optimizer: {rules: ["-all", "+replace-any-eq-with-in", "+use-indexes"]}}
            }).explain();

            var inPlan = db._createStatement({
                query: inQuery,
                bindVars: {},
                options: {optimizer: {rules: ["-all", "+use-indexes"]}}
            }).explain();

            var anyIndexNodes = findExecutionNodes(anyPlan.plan, "IndexNode");
            var inIndexNodes = findExecutionNodes(inPlan.plan, "IndexNode");

            assertTrue(anyIndexNodes.length > 0,
                "ANY == (transformed to IN) should use index");
            assertTrue(inIndexNodes.length > 0,
                "IN should use index");

            var anyResult = db._query(anyQuery, {}, 
                {optimizer: {rules: ["-all", "+replace-any-eq-with-in", "+use-indexes"]}}).toArray();
            var inResult = db._query(inQuery, {}, 
                {optimizer: {rules: ["-all", "+use-indexes"]}}).toArray();

            assertEqual(anyResult.length, inResult.length,
                "ANY == and IN should return same number of results");
        }
    };
}

jsunity.run(NewAqlReplaceAnyWithINTestSuite);

return jsunity.done();

