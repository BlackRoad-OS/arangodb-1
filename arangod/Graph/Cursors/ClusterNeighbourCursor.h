#pragma once

#include <cstdint>
#include <memory>
#include <vector>
#include "Aql/TraversalStats.h"
#include "Cluster/ClusterTypes.h"
#include "Graph/Providers/BaseProviderOptions.h"
#include "Network/Methods.h"

namespace arangodb::graph {

struct ExpansionInfo;

template<typename Step>
struct ClusterNeighbourCursor {
  using EngineRequest = std::pair<ServerID, futures::Future<network::Response>>;
  ClusterNeighbourCursor(Step step, size_t position,
                         std::vector<EngineRequest> requests,
                         arangodb::transaction::Methods* trx,
                         ClusterBaseProviderOptions& options,
                         aql::TraversalStats& stats)
      : _step{step},
        _position{position},
        _requests{std::move(requests)},
        _trx{trx},
        _opts{options},
        _stats{stats} {}
  auto next() -> std::vector<Step>;
  auto hasMore() -> bool;
  auto markForDeletion() -> void { _deletable = true; };

 public:
  template<typename S, typename Inspector>
  friend auto inspect(Inspector& f, ClusterNeighbourCursor<S>& x);
  bool _deletable = false;

 private:
  Step _step;
  size_t _position;
  std::vector<EngineRequest> _requests;
  arangodb::transaction::Methods* _trx;
  ClusterBaseProviderOptions& _opts;
  aql::TraversalStats& _stats;
};
template<typename Step, typename Inspector>
auto inspect(Inspector& f, ClusterNeighbourCursor<Step>& x) {
  return f.object(x).fields(f.field("step", x._step));
}

}  // namespace arangodb::graph
