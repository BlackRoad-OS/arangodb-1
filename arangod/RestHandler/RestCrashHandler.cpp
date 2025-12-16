////////////////////////////////////////////////////////////////////////////////
/// DISCLAIMER
///
/// Copyright 2014-2025 ArangoDB GmbH, Cologne, Germany
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
/// @author Jure Bajic
////////////////////////////////////////////////////////////////////////////////

// #include "RestCrashHandler.h"

// #include "CrashHandler/CrashHandler.h"
// #include "Utils/ExecContext.h"

using namespace arangodb;
using namespace arangodb::rest;

RestCrashHandler::RestCrashHandler(ArangodServer& server,
                                   GeneralRequest* request,
                                   GeneralResponse* response)
    : RestBaseHandler(server, request, response) {}

RestStatus RestCrashHandler::execute() {
  // Require admin access
  if (!ExecContext::current().isAdminUser()) {
    generateError(rest::ResponseCode::FORBIDDEN, TRI_ERROR_HTTP_FORBIDDEN,
                  "you need admin rights for crash management operations");
    return RestStatus::DONE;
  }

  std::vector<std::string> const& suffixes = _request->suffixes();

  if (suffixes.empty()) {
    // /_admin/crashes - list all crashes
    handleListCrashes();
  } else if (suffixes.size() == 1) {
    // /_admin/crashes/{id}
    std::string const& crashId = suffixes[0];

    if (_request->requestType() == rest::RequestType::GET) {
      handleGetCrash(crashId);
    } else if (_request->requestType() == rest::RequestType::DELETE_REQ) {
      handleDeleteCrash(crashId);
    } else {
      generateError(rest::ResponseCode::METHOD_NOT_ALLOWED,
                    TRI_ERROR_HTTP_METHOD_NOT_ALLOWED);
    }
  } else {
    generateError(rest::ResponseCode::NOT_FOUND, TRI_ERROR_HTTP_NOT_FOUND);
  }

  return RestStatus::DONE;
}

void RestCrashHandler::handleListCrashes() {
  if (_request->requestType() != rest::RequestType::GET) {
    generateError(rest::ResponseCode::METHOD_NOT_ALLOWED,
                  TRI_ERROR_HTTP_METHOD_NOT_ALLOWED);
    return;
  }

  auto crashes = CrashHandler::listCrashes();

  VPackBuilder builder;
  {
    VPackObjectBuilder guard(&builder);
    builder.add(VPackValue("crashes"));
    {
      VPackArrayBuilder guard2(&builder);
      for (auto const& crashId : crashes) {
        builder.add(VPackValue(crashId));
      }
    }
  }
  generateOk(rest::ResponseCode::OK, builder.slice());
}

void RestCrashHandler::handleGetCrash(std::string const& crashId) {
  auto contents = CrashHandler::getCrashContents(crashId);

  if (contents.empty()) {
    generateError(rest::ResponseCode::NOT_FOUND, TRI_ERROR_HTTP_NOT_FOUND,
                  "crash directory not found");
    return;
  }

  VPackBuilder builder;
  {
    VPackObjectBuilder guard(&builder);
    builder.add("crashId", VPackValue(crashId));
    builder.add(VPackValue("files"));
    {
      VPackObjectBuilder guard2(&builder);
      for (auto const& [filename, content] : contents) {
        builder.add(filename, VPackValue(content));
      }
    }
  }
  generateOk(rest::ResponseCode::OK, builder.slice());
}

void RestCrashHandler::handleDeleteCrash(std::string const& crashId) {
  bool deleted = CrashHandler::deleteCrash(crashId);

  if (!deleted) {
    generateError(rest::ResponseCode::NOT_FOUND, TRI_ERROR_HTTP_NOT_FOUND,
                  "crash directory not found");
    return;
  }

  VPackBuilder builder;
  {
    VPackObjectBuilder guard(&builder);
    builder.add("deleted", VPackValue(true));
    builder.add("crashId", VPackValue(crashId));
  }
  generateOk(rest::ResponseCode::OK, builder.slice());
}
