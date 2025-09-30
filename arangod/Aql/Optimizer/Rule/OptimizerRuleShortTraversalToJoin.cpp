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
#include "Aql/ExecutionNode/ExecutionNode.h"
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
#include "Indexes/Index.h"
#include "Logger/LogMacros.h"

using namespace arangodb;
using namespace arangodb::aql;
using namespace arangodb::containers;
using EN = arangodb::aql::ExecutionNode;

#define LOG_RULE LOG_DEVEL_IF(true)

namespace {}

void arangodb::aql::shortTraversalToJoinRule(
    Optimizer* opt, std::unique_ptr<ExecutionPlan> plan,
    OptimizerRule const& rule) {
  auto modified = false;

  LOG_RULE << "shortTraversalToJoin executed";

  auto traversalNodes = containers::SmallVector<ExecutionNode*, 8>{};
  plan->findNodesOfType(traversalNodes, ExecutionNode::TRAVERSAL, true);

  if (traversalNodes.empty()) {
    // no traversals present
    opt->addPlan(std::move(plan), rule, false);
    return;
  }

  for (auto const& node : traversalNodes) {
    auto* traversal = EN::castTo<TraversalNode*>(node);

    auto const* opts = traversal->options();

    TRI_ASSERT(opts != nullptr);

    if (opts->minDepth == 1 and opts->maxDepth == 1) {
      LOG_RULE << "FOUND ONE DEPZ TRAVERSAL";
      LOG_RULE << "prune " << opts->usesPrune()
               << " postFilter: " << opts->usesPostFilter()
               << " depth: " << opts->hasDepthLookupInfo();
    }
  }

  opt->addPlan(std::move(plan), rule, modified);
}
