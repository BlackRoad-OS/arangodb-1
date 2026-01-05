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
/// @author Andreas Streichardt <andreas@arangodb.com>
////////////////////////////////////////////////////////////////////////////////

#include "AuthenticationFeature.h"

#include "ApplicationFeatures/ApplicationServer.h"
#include "Auth/Handler.h"
#include "Auth/TokenCache.h"
#include "Auth/UserManagerImpl.h"
#include "AuthenticationOptionsProvider.h"
#include "Basics/FileUtils.h"
#include "Basics/StringUtils.h"
#include "Basics/application-exit.h"
#include "Cluster/ServerState.h"
#include "Logger/LogMacros.h"
#include "Logger/Logger.h"
#include "Logger/LoggerStream.h"
#include "ProgramOptions/Parameters.h"
#include "ProgramOptions/ProgramOptions.h"
#include "Random/RandomGenerator.h"
#include "RestServer/QueryRegistryFeature.h"

#include <limits>

using namespace arangodb::options;

namespace arangodb {

std::atomic<AuthenticationFeature*> AuthenticationFeature::INSTANCE = nullptr;

AuthenticationFeature::AuthenticationFeature(Server& server)
    : ArangodFeature{server, *this},
      _userManager(nullptr),
      _authCache(nullptr) {
  setOptional(false);
  startsAfter<application_features::BasicFeaturePhaseServer>();
}

AuthenticationFeature::~AuthenticationFeature() = default;

void AuthenticationFeature::collectOptions(
    std::shared_ptr<ProgramOptions> options) {
  AuthenticationOptionsProvider provider;
  provider.declareOptions(options, _options);
}

void AuthenticationFeature::validateOptions(
    std::shared_ptr<ProgramOptions> options) {
  AuthenticationOptionsProvider provider;
  provider.validateOptions(options, _options);

  if (!_options.jwtSecretKeyfileProgramOption.empty() ||
      !_options.jwtSecretFolderProgramOption.empty()) {
    Result res = loadJwtSecretsFromFile();
    if (res.fail()) {
      LOG_TOPIC("d3617", FATAL, Logger::STARTUP) << res.errorMessage();
      FATAL_ERROR_EXIT();
    }
  }
}

void AuthenticationFeature::prepare() {
  TRI_ASSERT(isEnabled());
  TRI_ASSERT(_userManager == nullptr);

  ServerState::RoleEnum role = ServerState::instance()->getRole();
  TRI_ASSERT(role != ServerState::RoleEnum::ROLE_UNDEFINED);
  if (ServerState::isSingleServer(role) || ServerState::isCoordinator(role)) {
    if (_userManager == nullptr) {
      _userManager = std::make_unique<auth::UserManagerImpl>(server());
    }

    TRI_ASSERT(_userManager != nullptr);
  } else {
    LOG_TOPIC("713c0", DEBUG, Logger::AUTHENTICATION)
        << "Not creating user manager";
  }

  TRI_ASSERT(_authCache == nullptr);
  _authCache = std::make_unique<auth::TokenCache>(
      _userManager.get(), _options.authenticationTimeout);

  if (_options.jwtSecretProgramOption.empty()) {
    LOG_TOPIC("43396", INFO, Logger::AUTHENTICATION)
        << "Jwt secret not specified, generating...";
    uint16_t m = 254;
    for (size_t i = 0; i < kMaxSecretLength; i++) {
      _options.jwtSecretProgramOption +=
          static_cast<char>(1 + RandomGenerator::interval(m));
    }
  }

#ifdef USE_ENTERPRISE
  _authCache->setJwtSecrets(_options.jwtSecretProgramOption,
                            _options.jwtPassiveSecrets);
#else
  _authCache->setJwtSecret(_options.jwtSecretProgramOption);
#endif

  INSTANCE.store(this, std::memory_order_release);
}

void AuthenticationFeature::start() {
  TRI_ASSERT(isEnabled());
  std::ostringstream out;

  out << "Authentication is turned " << (_options.active ? "on" : "off");

  if (_options.active && _options.authenticationSystemOnly) {
    out << " (system only)";
  }

#ifdef ARANGODB_HAVE_DOMAIN_SOCKETS
  out << ", authentication for unix sockets is turned "
      << (_options.authenticationUnixSockets ? "on" : "off");
#endif

  LOG_TOPIC("3844e", INFO, arangodb::Logger::AUTHENTICATION) << out.str();
}

void AuthenticationFeature::unprepare() {
  INSTANCE.store(nullptr, std::memory_order_relaxed);
}

AuthenticationFeature* AuthenticationFeature::instance() noexcept {
  return INSTANCE.load(std::memory_order_acquire);
}

bool AuthenticationFeature::isActive() const noexcept {
  return _options.active && isEnabled();
}

bool AuthenticationFeature::authenticationUnixSockets() const noexcept {
  return _options.authenticationUnixSockets;
}

bool AuthenticationFeature::authenticationSystemOnly() const noexcept {
  return _options.authenticationSystemOnly;
}

/// @return Cache to deal with authentication tokens
auth::TokenCache& AuthenticationFeature::tokenCache() const noexcept {
  TRI_ASSERT(_authCache);
  return *_authCache.get();
}

/// @brief user manager may be null on DBServers and Agency
/// @return user manager singleton
auth::UserManager* AuthenticationFeature::userManager() const noexcept {
  return _userManager.get();
}

bool AuthenticationFeature::hasUserdefinedJwt() const {
  std::lock_guard<std::mutex> guard(_jwtSecretsLock);
  return !_options.jwtSecretProgramOption.empty();
}

#ifdef USE_ENTERPRISE
/// verification only secrets
std::pair<std::string, std::vector<std::string>>
AuthenticationFeature::jwtSecrets() const {
  std::lock_guard<std::mutex> guard(_jwtSecretsLock);
  return {_options.jwtSecretProgramOption, _options.jwtPassiveSecrets};
}
#endif

Result AuthenticationFeature::loadJwtSecretsFromFile() {
  std::lock_guard<std::mutex> guard(_jwtSecretsLock);
  if (!_options.jwtSecretFolderProgramOption.empty()) {
    return loadJwtSecretFolder();
  } else if (!_options.jwtSecretKeyfileProgramOption.empty()) {
    return loadJwtSecretKeyfile();
  }
  return Result(TRI_ERROR_BAD_PARAMETER, "no JWT secret file was specified");
}

#ifdef ARANGODB_USE_GOOGLE_TESTS
void AuthenticationFeature::setUserManager(
    std::unique_ptr<auth::UserManager> um) {
  _userManager.swap(um);
}
#endif  // ARANGODB_USE_GOOGLE_TESTS

/// load JWT secret from file specified at startup
Result AuthenticationFeature::loadJwtSecretKeyfile() {
  try {
    // Note that the secret is trimmed for whitespace, because whitespace
    // at the end of a file can easily happen. We do not base64-encode,
    // though, so the bytes count as given. Zero bytes might be a problem
    // here.
    std::string contents =
        basics::FileUtils::slurp(_options.jwtSecretKeyfileProgramOption);
    _options.jwtSecretProgramOption =
        basics::StringUtils::trim(contents, " \t\n\r");
  } catch (std::exception const& ex) {
    std::string msg("unable to read content of jwt-secret file '");
    msg.append(_options.jwtSecretKeyfileProgramOption)
        .append("': ")
        .append(ex.what())
        .append(". please make sure the file/directory is readable for the ")
        .append("arangod process and user");
    return Result(TRI_ERROR_CANNOT_READ_FILE, std::move(msg));
  }
  return Result();
}

/// load JWT secrets from folder
Result AuthenticationFeature::loadJwtSecretFolder() try {
  TRI_ASSERT(!_options.jwtSecretFolderProgramOption.empty());

  LOG_TOPIC("4922f", INFO, arangodb::Logger::AUTHENTICATION)
      << "loading JWT secrets from folder "
      << _options.jwtSecretFolderProgramOption;

  auto list =
      basics::FileUtils::listFiles(_options.jwtSecretFolderProgramOption);

  // filter out empty filenames, hidden files, tmp files and symlinks
  list.erase(std::remove_if(list.begin(), list.end(),
                            [this](std::string const& file) {
                              if (file.empty() || file[0] == '.') {
                                return true;
                              }
                              if (file.ends_with(".tmp")) {
                                return true;
                              }
                              auto p = basics::FileUtils::buildFilename(
                                  _options.jwtSecretFolderProgramOption, file);
                              if (basics::FileUtils::isSymbolicLink(p)) {
                                return true;
                              }
                              return false;
                            }),
             list.end());

  if (list.empty()) {
    return Result(TRI_ERROR_BAD_PARAMETER, "empty JWT secrets directory");
  }

  auto slurpy = [&](std::string const& file) {
    auto p = basics::FileUtils::buildFilename(
        _options.jwtSecretFolderProgramOption, file);
    std::string contents = basics::FileUtils::slurp(p);
    return basics::StringUtils::trim(contents, " \t\n\r");
  };

  std::sort(std::begin(list), std::end(list));
  std::string activeSecret = slurpy(list[0]);

  const std::string msg = "Given JWT secret too long. Max length is 64";
  if (activeSecret.length() > kMaxSecretLength) {
    return Result(TRI_ERROR_BAD_PARAMETER, msg);
  }

#ifdef USE_ENTERPRISE
  std::vector<std::string> passiveSecrets;
  if (list.size() > 1) {
    list.erase(list.begin());
    for (auto const& file : list) {
      std::string secret = slurpy(file);
      if (secret.length() > kMaxSecretLength) {
        return Result(TRI_ERROR_BAD_PARAMETER, msg);
      }
      if (!secret.empty()) {  // ignore
        passiveSecrets.push_back(std::move(secret));
      }
    }
  }
  _options.jwtPassiveSecrets = std::move(passiveSecrets);

  LOG_TOPIC("4a34f", INFO, arangodb::Logger::AUTHENTICATION)
      << "have " << _options.jwtPassiveSecrets.size() << " passive JWT secrets";
#endif

  _options.jwtSecretProgramOption = std::move(activeSecret);

  return Result();
} catch (basics::Exception const& ex) {
  std::string msg("unable to read content of jwt-secret-folder '");
  msg.append(_options.jwtSecretFolderProgramOption)
      .append("': ")
      .append(ex.what())
      .append(". please make sure the file/directory is readable for the ")
      .append("arangod process and user");
  return Result(TRI_ERROR_CANNOT_READ_FILE, std::move(msg));
}

}  // namespace arangodb
