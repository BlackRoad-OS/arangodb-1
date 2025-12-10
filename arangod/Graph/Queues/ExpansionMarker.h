////////////////////////////////////////////////////////////////////////////////
/// DISCLAIMER
///
/// Copyright 2014-2024 ArangoDB GmbH, Cologne, Germany
/// Copyright 2004-2014 triAGENS GmbH, Cologne, Germany
///
/// Licensed under the Business Source License 1.1 (the "License");
/// you may not use this file except in compliance with the License.
/// You may obtain a copy of the License at
///
///     https://github.com/arangodb/arangodb/blob/devel/LICENSE
///
/// Unless required by applicable law or agreed to in writing, software
/// distributed under the License is distributed on an "AS IS" BASIS,
/// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
/// See the License for the specific language governing permissions and
/// limitations under the License.
///
/// Copyright holder is ArangoDB GmbH, Cologne, Germany
///
/// @author Julia Volmer
////////////////////////////////////////////////////////////////////////////////
#pragma once

#include <variant>
#include <memory>
#include <vector>
#include "Inspection/Types.h"
#include "Aql/TraversalStats.h"

namespace arangodb::aql {
class TraversalStats;
}

namespace arangodb::graph {
struct ExpansionInfo;

using CursorId = std::size_t;

/**
   Marker struct for queues to do an expansion when such a type is popped.
 **/
struct Expansion {
  CursorId id;
  std::size_t from;
};
template<typename Inspector>
auto inspect(Inspector& f, Expansion& x) {
  return f.object(x).fields(f.field("id", x.id), f.field("from", x.from));
}

template<typename Step>
struct QueueEntry : std::variant<Step, Expansion> {};
template<typename Step, typename Inspector>
auto inspect(Inspector& f, QueueEntry<Step>& x) {
  return f.variant(x).unqualified().alternatives(
      inspection::inlineType<Step>(), inspection::inlineType<Expansion>());
}

template<typename T>
concept NeighbourCursor = requires(T t,
                                   std::shared_ptr<aql::TraversalStats> stats,
                                   uint64_t depth) {
  {
    t.next(stats)
    } -> std::convertible_to<std::shared_ptr<std::vector<ExpansionInfo>>>;
  { t.hasMore(depth) } -> std::convertible_to<bool>;
};

template<typename Step, NeighbourCursor Cursor>
struct NewQueueEntry : std::variant<Step, std::reference_wrapper<Cursor>> {};
template<typename Step, NeighbourCursor Cursor, typename Inspector>
auto inspect(Inspector& f, NewQueueEntry<Step, Cursor>& x) {
  return f.variant(x).unqualified().alternatives(
      inspection::inlineType<Step>(), inspection::inlineType<Cursor>());
}

}  // namespace arangodb::graph
