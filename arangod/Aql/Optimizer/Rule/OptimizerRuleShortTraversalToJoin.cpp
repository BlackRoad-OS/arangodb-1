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
#include "Aql/Collection.h"
#include "Aql/Condition.h"
#include "Aql/ExecutionEngine.h"
#include "Aql/ExecutionNode/CalculationNode.h"
#include "Aql/ExecutionNode/EnumerateCollectionNode.h"
#include "Aql/ExecutionNode/ExecutionNode.h"
#include "Aql/ExecutionNode/FilterNode.h"
#include "Aql/ExecutionNode/IndexNode.h"
#include "Aql/ExecutionNode/JoinNode.h"
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

#include <functional>

using namespace arangodb;
using namespace arangodb::aql;
using namespace arangodb::containers;
using EN = arangodb::aql::ExecutionNode;

#define LOG_RULE LOG_DEVEL_IF(true)

namespace {
auto buildSnippet(std::unique_ptr<ExecutionPlan>& plan,
                  TraversalNode* traversal) {
  auto* ast = plan->getAst();
  /* Replace the traversal node with this snippet */

  Variable const* vertexOutputVariable = traversal->vertexOutVariable();
  Variable const* edgeOutputVariable = traversal->edgeOutVariable();
  Variable const* pathOutputVariable = traversal->pathOutVariable();

  // Enumerate Edge Collection
  // TODO: this is not correct yet
  Collection* targetVertexCollection = traversal->vertexColls()[0];
  Collection* edgeCollection = traversal->edgeColls()[0];

  auto enumerateEdges = plan->createNode<EnumerateCollectionNode>(
      plan.get(), plan->nextId(), edgeCollection, edgeOutputVariable,
      false /*random*/, IndexHint{});
  enumerateEdges->addDependency(traversal->getFirstDependency());
  traversal->removeDependencies();

  // for FILTER e._from == startVertex._id
  auto startVertexCondition = std::invoke([&]() -> AstNode* {
    auto rhs = std::invoke([&]() -> AstNode const* {
      if (traversal->usesInVariable()) {
        auto ref = ast->createNodeReference(traversal->inVariable());
        return ast->createNodeAttributeAccess(ref, StaticStrings::IdString);
      } else {
        auto const& sv = traversal->getStartVertex();
        return ast->createNodeValueString(sv.c_str(), sv.size());
      }
    });

    auto ref = ast->createNodeReference(edgeOutputVariable);
    auto const* access =
        ast->createNodeAttributeAccess(ref, StaticStrings::FromString);

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

  // TODO: calculate path
  auto calculatePath = plan->createNode<CalculationNode>(
      plan.get(), plan->nextId(),
      std::make_unique<Expression>(ast, targetVertexCondition),
      pathOutputVariable);
  calculatePath->addDependency(filterTargetVertex);

  auto parent = traversal->getFirstParent();
  parent->removeDependencies();
  parent->addDependency(calculatePath);
}
/*

  INPUTVAR: startVertex

  FOR v,e,p IN 1..1 OUTBOUND startVertex $graphSubject
      ...

  OUTPUTVARS v (vertex in target vertex collection)
             e (current edge)
             p (object with vertices and edges)

->



 FOR e IN $edgeColl
   FILTER e._from == startVertex
   FOR v IN $vertexColl
     FILTER v._id == e._from
     p = ...

 */
}  // namespace

void arangodb::aql::shortTraversalToJoinRule(
    Optimizer* opt, std::unique_ptr<ExecutionPlan> plan,
    OptimizerRule const& rule) {
  auto modified = false;
  auto builder = VPackBuilder{};

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

    if (traversal->vertexColls().size() ==
            1 and  // TODO: not quite correct; one collection either side is ok;
                   // not sure how to tell this
        traversal->edgeColls().size() == 1 and  //
        opts->minDepth == 1 and                 //
        opts->maxDepth == 1 and                 //
        true /* direction is important here */) {
      //      buildSnippet();

      auto parent = traversal->getFirstParent();
      auto dep = traversal->getFirstDependency();

      builder.clear();
      parent->toVelocyPack(builder, 0);
      LOG_RULE << "parent " << builder.toJson();

      builder.clear();
      dep->toVelocyPack(builder, 0);
      LOG_RULE << "dep " << builder.toJson();

      buildSnippet(plan, traversal);

      builder.clear();
      plan->show();

      modified = true;
      //      THROW_ARANGO_EXCEPTION_MESSAGE(
      //    TRI_ERROR_QUERY_PARSE,
      //    fmt::format("1 step traversal replacement fired"));
    }
  }
  opt->addPlan(std::move(plan), rule, modified);
}
