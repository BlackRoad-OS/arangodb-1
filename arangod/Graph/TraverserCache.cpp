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
/// @author Michael Hackstein
////////////////////////////////////////////////////////////////////////////////

#include "TraverserCache.h"

#include "ApplicationFeatures/ApplicationServer.h"
#include "Aql/AqlValue.h"
#include "Aql/Query.h"
#include "Basics/StringHeap.h"
#include "Basics/VelocyPackHelper.h"
#include "Cluster/ServerState.h"
#include "Graph/BaseOptions.h"
#include "Graph/EdgeDocumentToken.h"
#include "Logger/LogMacros.h"
#include "Logger/Logger.h"
#include "Logger/LoggerStream.h"
#include "RestServer/QueryRegistryFeature.h"
#include "StorageEngine/PhysicalCollection.h"
#include "StorageEngine/TransactionState.h"
#include "Transaction/Methods.h"
#include "Transaction/Options.h"
#include "VocBase/LogicalCollection.h"

#include <velocypack/Builder.h>
#include <velocypack/HashedStringRef.h>
#include <velocypack/Slice.h>

using namespace arangodb;
using namespace arangodb::graph;

namespace {
constexpr size_t costPerPersistedString =
    sizeof(void*) + sizeof(arangodb::velocypack::HashedStringRef);
}  // namespace

TraverserCache::TraverserCache(aql::QueryContext& query, BaseOptions* opts)
    : _query(query),
      _trx(opts->trx()),
      _insertedDocuments(0),
      _filtered(0),
      _cursorsCreated(0),
      _cursorsRearmed(0),
      _cacheHits(0),
      _cacheMisses(0),
      _stringHeap(
          query.resourceMonitor(),
          4096), /* arbitrary block-size, may be adjusted for performance */
      _baseOptions(opts),
      _allowImplicitCollections(ServerState::instance()->isSingleServer() &&
                                !_query.vocbase()
                                     .server()
                                     .getFeature<QueryRegistryFeature>()
                                     .requireWith()) {}

TraverserCache::~TraverserCache() { clear(); }

void TraverserCache::clear() {
  _query.resourceMonitor().decreaseMemoryUsage(_persistedStrings.size() *
                                               ::costPerPersistedString);

  _persistedStrings.clear();
  _docBuilder.clear();
  _stringHeap.clear();
}
