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
#include "RestHandler.h"

#include "Containers/Forest/forest.h"
#include "ApplicationFeatures/ApplicationServer.h"
#include "Cluster/ClusterFeature.h"
#include "Cluster/ClusterInfo.h"
#include "Cluster/ServerState.h"
#include "Network/ConnectionPool.h"
#include "Network/Methods.h"
#include "Network/NetworkFeature.h"
#include "Network/RequestOptions.h"
#include "Rest/CommonDefines.h"

using namespace arangodb::async_registry;

RestHandler::RestHandler(ArangodServer& server, GeneralRequest* request,
                         GeneralResponse* response)
    : RestVocbaseBaseHandler(server, request, response),
      _feature(server.getFeature<Feature>()) {}

auto RestHandler::executeAsync() -> futures::Future<futures::Unit> {
  if (!ExecContext::current().isSuperuser()) {
    generateError(rest::ResponseCode::FORBIDDEN, TRI_ERROR_HTTP_FORBIDDEN,
                  "you need super user rights for log operations");
  }

  if (_request->requestType() != rest::RequestType::GET) {
    generateError(rest::ResponseCode::METHOD_NOT_ALLOWED,
                  TRI_ERROR_HTTP_METHOD_NOT_ALLOWED);
    co_return;
  }

  // forwarding
  bool foundServerIdParameter;
  std::string const& serverId =
      _request->value("serverId", foundServerIdParameter);

  if (ServerState::instance()->isCoordinator() && foundServerIdParameter) {
    if (serverId != ServerState::instance()->getId()) {
      // not ourselves! - need to pass through the request
      auto& ci = server().getFeature<ClusterFeature>().clusterInfo();

      bool found = false;
      for (auto const& srv : ci.getServers()) {
        // validate if server id exists
        if (srv.first == serverId) {
          found = true;
          break;
        }
      }

      if (!found) {
        generateError(rest::ResponseCode::NOT_FOUND,
                      TRI_ERROR_HTTP_BAD_PARAMETER,
                      "unknown serverId supplied.");
        co_return;
      }

      NetworkFeature const& nf = server().getFeature<NetworkFeature>();
      network::ConnectionPool* pool = nf.pool();
      if (pool == nullptr) {
        THROW_ARANGO_EXCEPTION(TRI_ERROR_SHUTTING_DOWN);
      }
      network::RequestOptions options;
      options.timeout = network::Timeout(30.0);
      options.database = _request->databaseName();
      options.parameters = _request->parameters();

      auto f = network::sendRequestRetry(
          pool, "server:" + serverId, fuerte::RestVerb::Get,
          _request->requestPath(), VPackBuffer<uint8_t>{}, options);
      co_await std::move(f).thenValue(
          [self = std::dynamic_pointer_cast<RestHandler>(shared_from_this())](
              network::Response const& r) {
            if (r.fail()) {
              self->generateError(r.combinedResult());
            } else {
              self->generateResult(rest::ResponseCode::OK, r.slice());
            }
          });
      co_return;
    }
  }

  auto lock_guard = co_await _feature.asyncLock();

  // do actual work
  auto promises = all_undeleted_promises().index_by_awaitee();
  generateResult(rest::ResponseCode::OK, getStacktraceData(promises).slice());
  co_return;
}
