////////////////////////////////////////////////////////////////////////////////
/// DISCLAIMER
///
/// Copyright 2014-2023 ArangoDB GmbH, Cologne, Germany
/// Copyright 2004-2014 triAGENS GmbH, Cologne, Germany
///
/// Licensed under the Apache License, Version 2.0 (the "License");
/// you may not use this file except in compliance with the License.
/// You may obtain a copy of the License at
///
///     http://www.apache.org/licenses/LICENSE-2.0
///
/// Unless required by applicable law or agreed to in writing, software
/// distributed under the License is distributed on an "AS IS" BASIS,
/// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
/// See the License for the specific language governing permissions and
/// limitations under the License.
///
/// Copyright holder is ArangoDB GmbH, Cologne, Germany
////////////////////////////////////////////////////////////////////////////////

#include "Aql/Ast.h"
#include "Aql/AstNode.h"
#include "Aql/Collection.h"
#include "Aql/Condition.h"
#include "Aql/ExecutionEngine.h"
#include "Aql/ExecutionNode/CalculationNode.h"
#include "Aql/ExecutionNode/EnumerateCollectionNode.h"
#include "Aql/ExecutionNode/ExecutionNode.h"
#include "Aql/ExecutionNode/FilterNode.h"
#include "Aql/ExecutionNode/IndexNode.h"
#include "Aql/ExecutionNode/JoinNode.h"
#include "Aql/ExecutionNode/MaterializeNode.h"
#include "Aql/ExecutionNode/MaterializeRocksDBNode.h"
#include "Aql/ExecutionNode/TraversalNode.h"
#include "Aql/ExecutionNode/SubqueryNode.h"
#include "Aql/ExecutionPlan.h"
#include "Aql/Expression.h"
#include "Aql/Optimizer.h"
#include "Aql/OptimizerRules.h"
#include "Aql/OptimizerUtils.h"
#include "Aql/Query.h"
#include "Basics/StaticStrings.h"
#include "Indexes/Index.h"
#include "Logger/LogMacros.h"
#include "VocBase/voc-types.h"

#include <functional>

using namespace arangodb;
using namespace arangodb::aql;
using namespace arangodb::containers;
using EN = arangodb::aql::ExecutionNode;

#define LOG_RULE LOG_DEVEL_IF(true)

namespace {

/*

  INPUTVAR: startVertex can be a string, an object, or a
            variable (that contains a string or a document...).

  FOR v,e,p IN 1..1 OUTBOUND startVertex $graphSubject
      ...

  OUTPUTVARS v (vertex in target vertex collection)
             e (current edge)
             p = {vertices: [startVertex, v], edges: [e]} (object with vertices
and edges; might have to materialize startVertex?))


->



 FOR e IN $edgeColl
   FILTER e._from == startVertex (here we need the vertex id)
   FOR v IN $vertexColl
     FILTER v._id == e._from
     p = ...


     But if additional filters happen we need them to happen possibly on v.



LET vids = [ id1, id2, id3 ]
FOR s IN vids
  FOR v,e,p IN 1..1 OUTBOUND s  GRAPH G
  // Whats the semantics here, is FILTER v.x === foo applied to startvertex?
    FILTER v.blubb... -> FILTER DOCUMENT(s).blubb... AND v.blubb
    FILTER e.blabb -> no problem
    FILTER p.vertices[*].yadda -> no problem (I think, could rewirte to 2
filters again) FILTER p.edges[*].uymml -> no problem (could rewrite to FILTER
e.uymml)


// Should this really be done as an operation anyway? What would be the
performance impact?

// LET id = DOCUMENT_ID_FROM(x)


FOR v,e,p IN 1..1 OUTBOUND "v/foo" GRAPH G ...

FOR v,e,p IN 1..1 OUTBOUND s GRAPH g

->

LET s_id = DOCUMENT_ID_FROM(s);
FOR e IN E
  FILTER e._from == s_id
  FOR v IN vertex_collection
    FILTER e._to == v._id (// (or such a vertex does not exist; now one could
check whether v is filtered by equality for an attribute, which would ensure
correct semantics)

 */
auto buildSnippet(std::unique_ptr<ExecutionPlan>& plan,
                  TraversalNode* traversal) {
  auto* ast = plan->getAst();
  /* Replace the traversal node with this snippet */

  Variable const* startVertexDocumentVariable =
      ast->variables()
          ->createTemporaryVariable(); /* or a constant :rolling eyes: */

  Variable const* vertexOutputVariable = traversal->vertexOutVariable();
  Variable const* edgeOutputVariable = traversal->edgeOutVariable();
  Variable const* pathOutputVariable = traversal->pathOutVariable();

  // Traversal syntax allows not to give edge or path variable in which case
  // these variables are null here.
  // The snippet needs them though, so we create them again.
  // TODO: maybe name them e and p in the plan
  if (edgeOutputVariable == nullptr) {
    edgeOutputVariable = ast->variables()->createTemporaryVariable();
  }

  // TODO: if this is null we can just skip computing the path output further
  // down.
  if (pathOutputVariable == nullptr) {
    pathOutputVariable = ast->variables()->createTemporaryVariable();
  }

  Collection* sourceVertexCollection = traversal->vertexColls()[0];
  Collection* targetVertexCollection = traversal->vertexColls()[0];
  Collection* edgeCollection = traversal->edgeColls()[0];

  LOG_DEVEL << "vertexColls";
  for (auto&& c : traversal->vertexColls()) {
    LOG_RULE << c->name();
  }
  LOG_DEVEL << "///";

  LOG_RULE << "svc: " << sourceVertexCollection->name();
  LOG_RULE << "tvc: " << targetVertexCollection->name();
  LOG_RULE << "ecn: " << edgeCollection->name();

  // Calculate start vertex id
  Variable const* startVertexIdVariable =
      ast->variables()
          ->createTemporaryVariable(); /* or a constant :rolling eyes: */

  auto startVertexIdCalculation = std::invoke([&]() -> AstNode* {
    auto startVertex = std::invoke([&]() -> AstNode* {
      if (traversal->usesInVariable()) {
        // TODO: fun complication: we can get input via a variable, and that
        // variable might contain a string *or* an object with an ID.
        // That means that we actually have to extract the document id from a
        // variable here which requires a calculationnode
        return ast->createNodeReference(traversal->inVariable());
      } else {
        auto* sv = ast->resources().registerString(traversal->getStartVertex());
        return ast->createNodeValueString(sv,
                                          traversal->getStartVertex().size());
      }
    });

    auto args = ast->createNodeArray();
    args->addMember(startVertex);

    return ast->createNodeFunctionCall("TO_DOCUMENT_ID", args, true);
  });

  auto calculateStartVertexId = plan->createNode<CalculationNode>(
      plan.get(), plan->nextId(),
      std::make_unique<Expression>(ast, startVertexIdCalculation),
      startVertexIdVariable);
  calculateStartVertexId->addDependency(traversal->getFirstDependency());
  traversal->removeDependencies();

  // "materialize" start vertex
  auto enumerateStartVertex = plan->createNode<EnumerateCollectionNode>(
      plan.get(), plan->nextId(), sourceVertexCollection,
      startVertexDocumentVariable, false, IndexHint{});
  enumerateStartVertex->addDependency(calculateStartVertexId);

  //// FILTER startVertexDocumentVariable._id == startVertexId
  auto startVertexDocumentCondition = std::invoke([&]() -> AstNode* {
    auto ref = ast->createNodeReference(startVertexDocumentVariable);
    auto const* access =
        ast->createNodeAttributeAccess(ref, StaticStrings::IdString);

    auto const rhs = ast->createNodeReference(startVertexIdVariable);
    return ast->createNodeBinaryOperator(NODE_TYPE_OPERATOR_BINARY_EQ, access,
                                         rhs);
  });
  Variable const* startVertexDocumentConditionVariable =
      ast->variables()
          ->createTemporaryVariable(); /* or a constant :rolling eyes: */

  auto calculateStartVertexDocumentCondition =
      plan->createNode<CalculationNode>(
          plan.get(), plan->nextId(),
          std::make_unique<Expression>(ast, startVertexDocumentCondition),
          startVertexDocumentConditionVariable);
  calculateStartVertexDocumentCondition->addDependency(enumerateStartVertex);

  auto filterStartVertexDocument = plan->createNode<FilterNode>(
      plan.get(), plan->nextId(), startVertexDocumentConditionVariable);
  filterStartVertexDocument->addDependency(
      calculateStartVertexDocumentCondition);

  /////
  auto enumerateEdges = plan->createNode<EnumerateCollectionNode>(
      plan.get(), plan->nextId(), edgeCollection, edgeOutputVariable,
      false /*random*/, IndexHint{});
  enumerateEdges->addDependency(filterStartVertexDocument);

  // FILTER e._from == startVertex._id
  auto startVertexCondition = std::invoke([&]() -> AstNode* {
    auto ref = ast->createNodeReference(edgeOutputVariable);
    auto const* access =
        ast->createNodeAttributeAccess(ref, StaticStrings::FromString);

    auto const rhs = ast->createNodeReference(startVertexIdVariable);
    return ast->createNodeBinaryOperator(NODE_TYPE_OPERATOR_BINARY_EQ, access,
                                         rhs);
  });
  Variable const* startVertexConditionVariable =
      ast->variables()
          ->createTemporaryVariable(); /* or a constant :rolling eyes: */

  auto calculateStartVertexCondition = plan->createNode<CalculationNode>(
      plan.get(), plan->nextId(),
      std::make_unique<Expression>(ast, startVertexCondition),
      startVertexConditionVariable);
  calculateStartVertexCondition->addDependency(enumerateEdges);

  auto filterStartVertex = plan->createNode<FilterNode>(
      plan.get(), plan->nextId(), startVertexConditionVariable);
  filterStartVertex->addDependency(calculateStartVertexCondition);

  auto enumerateTargetVertices = plan->createNode<EnumerateCollectionNode>(
      plan.get(), plan->nextId(), targetVertexCollection, vertexOutputVariable,
      false /*random*/, IndexHint{});
  enumerateTargetVertices->addDependency(filterStartVertex);

  auto targetVertexCondition = std::invoke([&]() -> AstNode* {
    auto ref = ast->createNodeReference(edgeOutputVariable);
    auto const* access =
        ast->createNodeAttributeAccess(ref, StaticStrings::ToString);

    auto ref2 = ast->createNodeReference(vertexOutputVariable);
    auto const* rhs =
        ast->createNodeAttributeAccess(ref2, StaticStrings::IdString);
    return ast->createNodeBinaryOperator(NODE_TYPE_OPERATOR_BINARY_EQ, access,
                                         rhs);
  });

  // FILTER e._to == v._id
  Variable const* targetVertexConditionVariable =
      ast->variables()
          ->createTemporaryVariable(); /* or a constant :rolling eyes: */
  auto calculateTargetVertexCondition = plan->createNode<CalculationNode>(
      plan.get(), plan->nextId(),
      std::make_unique<Expression>(ast, targetVertexCondition),
      targetVertexConditionVariable);
  calculateTargetVertexCondition->addDependency(enumerateTargetVertices);

  auto filterTargetVertex = plan->createNode<FilterNode>(
      plan.get(), plan->nextId(), targetVertexConditionVariable);
  filterTargetVertex->addDependency(calculateTargetVertexCondition);

  auto calculatePathExpression = std::invoke([&]() -> AstNode* {
    auto* obj = ast->createNodeObject();

    auto* vertexArray = ast->createNodeArray();
    vertexArray->addMember(
        ast->createNodeReference(startVertexDocumentVariable));
    vertexArray->addMember(ast->createNodeReference(vertexOutputVariable));
    auto vertices = ast->createNodeObjectElement("vertices", vertexArray);
    obj->addMember(vertices);

    auto* edgeArray = ast->createNodeArray();
    edgeArray->addMember(ast->createNodeReference(edgeOutputVariable));
    auto edges = ast->createNodeObjectElement("edges", edgeArray);
    obj->addMember(edges);

    // TODO dummy weights
    return obj;
  });

  auto calculatePath = plan->createNode<CalculationNode>(
      plan.get(), plan->nextId(),
      std::make_unique<Expression>(ast, calculatePathExpression),
      pathOutputVariable);
  calculatePath->addDependency(filterTargetVertex);

  auto parent = traversal->getFirstParent();
  parent->removeDependencies();
  parent->addDependency(calculatePath);
}

// TODO: This function should explain why the optimisation rule
// is or is not applicable
auto isRuleApplicable(TraversalNode* traversal) -> bool {
  auto const* opts = traversal->options();

  // TODO: at the moment really only one vertex collection is good enough.
  // as we cannot distinguish which of the 2 collections would be from and
  // which would be to!
  // For experiments lets just :yolo: it and say the first one is from and
  // the second one is to
  if (traversal->isSmart()) {
    return false;
  }
  if (traversal->vertexColls().size() != 1) {
    return false;
  }
  if (traversal->edgeColls().size() != 1) {
    return false;
  }
  // TODO: I don't even.
  if (traversal->edgeColls().at(0) == traversal->vertexColls().at(0)) {
    return false;
  }
  if (opts->minDepth != 1) {
    return false;
  }
  if (opts->maxDepth != 1) {
    return false;
  }
  if (traversal->edgeDirections().at(0) != TRI_EDGE_OUT) {
    return false;
  }
  return true;
}
}  // namespace

void arangodb::aql::shortTraversalToJoinRule(
    Optimizer* opt, std::unique_ptr<ExecutionPlan> plan,
    OptimizerRule const& rule) {
  auto modified = false;

  auto traversalNodes = containers::SmallVector<ExecutionNode*, 8>{};
  plan->findNodesOfType(traversalNodes, ExecutionNode::TRAVERSAL, true);

  if (traversalNodes.empty()) {
    // no traversals present
    opt->addPlan(std::move(plan), rule, modified);
    return;
  }

  for (auto const& node : traversalNodes) {
    auto* traversal = EN::castTo<TraversalNode*>(node);
    auto const* opts = traversal->options();

    TRI_ASSERT(traversal != nullptr);
    TRI_ASSERT(opts != nullptr);

    if (isRuleApplicable(traversal)) {
      buildSnippet(plan, traversal);
      modified = true;
    }
  }
  opt->addPlan(std::move(plan), rule, modified);
}
