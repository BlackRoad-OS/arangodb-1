#pragma once

#include <cstdint>
#include <memory>
#include <vector>

namespace arangodb::graph {

struct ExpansionInfo;

template<typename Step>
struct ClusterNeighbourCursor {
  auto next() -> std::vector<Step> { return {}; }
  auto hasMore() -> bool { return false; };
  auto markForDeletion() -> void{};
};
template<typename Inspector, typename Step>
auto inspect(Inspector& f, ClusterNeighbourCursor<Step>& x) {
  return f.object(x).fields();
}

}  // namespace arangodb::graph
