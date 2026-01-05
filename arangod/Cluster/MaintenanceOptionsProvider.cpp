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
////////////////////////////////////////////////////////////////////////////////

#include "MaintenanceOptionsProvider.h"

#include "Basics/NumberOfCores.h"
#include "Logger/LogMacros.h"
#include "Logger/Logger.h"
#include "ProgramOptions/Parameters.h"
#include "ProgramOptions/ProgramOptions.h"

namespace arangodb {

using namespace arangodb::options;

void MaintenanceOptionsProvider::declareOptions(
    std::shared_ptr<ProgramOptions> options, MaintenanceOptions& opts) {
  // Initialize default values that depend on system state
  // Corresponds to lines 167-170 in MaintenanceFeature constructor
  opts.maintenanceThreadsMax =
      (std::max)(static_cast<uint32_t>(3),  // minThreadLimit
                 static_cast<uint32_t>(NumberOfCores::getValue() / 4 + 1));
  opts.maintenanceThreadsSlowMax = opts.maintenanceThreadsMax / 2;

  options->addOption(
      "--server.maintenance-threads",
      "The maximum number of threads available for maintenance actions.",
      new UInt32Parameter(&opts.maintenanceThreadsMax),
      arangodb::options::makeFlags(
          arangodb::options::Flags::DefaultNoComponents,
          arangodb::options::Flags::OnDBServer,
          arangodb::options::Flags::Uncommon,
          arangodb::options::Flags::Dynamic));

  options
      ->addOption(
          "--server.maximal-number-sync-shard-actions",
          "The maximum number of SynchronizeShard actions which may be queued "
          "at any given time.",
          new UInt64Parameter(&opts.maximalNumberOfSyncShardActionsQueued, 1, 1,
                              std::numeric_limits<uint64_t>::max()),
          arangodb::options::makeFlags(
              arangodb::options::Flags::DefaultNoComponents,
              arangodb::options::Flags::OnDBServer,
              arangodb::options::Flags::Uncommon))
      .setIntroducedIn(31205);

  options
      ->addOption("--server.maintenance-slow-threads",
                  "The maximum number of threads available for slow "
                  "maintenance actions (long SynchronizeShard and long "
                  "EnsureIndex).",
                  new UInt32Parameter(&opts.maintenanceThreadsSlowMax),
                  arangodb::options::makeFlags(
                      arangodb::options::Flags::DefaultNoComponents,
                      arangodb::options::Flags::OnDBServer,
                      arangodb::options::Flags::Uncommon,
                      arangodb::options::Flags::Dynamic))
      .setIntroducedIn(30803);

  options->addOption(
      "--server.maintenance-actions-block",
      "The minimum number of seconds finished actions block duplicates.",
      new Int32Parameter(&opts.secondsActionsBlock),
      arangodb::options::makeFlags(
          arangodb::options::Flags::DefaultNoComponents,
          arangodb::options::Flags::OnDBServer,
          arangodb::options::Flags::Uncommon));

  options->addOption(
      "--server.maintenance-actions-linger",
      "The minimum number of seconds finished actions remain in the deque.",
      new Int32Parameter(&opts.secondsActionsLinger),
      arangodb::options::makeFlags(
          arangodb::options::Flags::DefaultNoComponents,
          arangodb::options::Flags::OnDBServer,
          arangodb::options::Flags::Uncommon));

  options->addOption(
      "--cluster.resign-leadership-on-shutdown",
      "Create a resign leader ship job for this DB-Server on shutdown.",
      new BooleanParameter(&opts.resignLeadershipOnShutdown),
      arangodb::options::makeFlags(
          arangodb::options::Flags::DefaultNoComponents,
          arangodb::options::Flags::OnDBServer,
          arangodb::options::Flags::Uncommon));
}

void MaintenanceOptionsProvider::validateOptions(
    std::shared_ptr<ProgramOptions> options, MaintenanceOptions& opts) {
  // Corresponds to lines 260-294 in MaintenanceFeature::validateOptions

  // Explanation: There must always be at least 3 maintenance threads.
  // The first one only does actions which are labelled "fast track".
  // The next few threads do "slower" actions, but never work on very slow
  // actions which came into being by rescheduling. If they stumble on
  // an actions which seems to take long, they give up and reschedule
  // with a special slow priority, such that the action is eventually
  // executed by the slow threads. We can configure both the total number
  // of threads as well as the number of slow threads. The number of slow
  // threads must always be at most N-2 if N is the total number of threads.
  // The default for the slow threads is N/2, unless the user has used
  // an override.
  constexpr uint32_t minThreadLimit = 3;
  constexpr uint32_t maxThreadLimit = 64;

  if (opts.maintenanceThreadsMax < minThreadLimit) {
    LOG_TOPIC("37726", WARN, Logger::MAINTENANCE)
        << "Need at least" << minThreadLimit << "maintenance-threads";
    opts.maintenanceThreadsMax = minThreadLimit;
  } else if (opts.maintenanceThreadsMax > maxThreadLimit) {
    LOG_TOPIC("8fb0e", WARN, Logger::MAINTENANCE)
        << "maintenance-threads limited to " << maxThreadLimit;
    opts.maintenanceThreadsMax = maxThreadLimit;
  }
  if (!options->processingResult().touched("server.maintenance-slow-threads")) {
    opts.maintenanceThreadsSlowMax = opts.maintenanceThreadsMax / 2;
  }
  if (opts.maintenanceThreadsSlowMax + 2 > opts.maintenanceThreadsMax) {
    opts.maintenanceThreadsSlowMax = opts.maintenanceThreadsMax - 2;
    LOG_TOPIC("54251", WARN, Logger::MAINTENANCE)
        << "maintenance-slow-threads limited to "
        << opts.maintenanceThreadsSlowMax;
  }
  if (opts.maintenanceThreadsSlowMax == 0) {
    opts.maintenanceThreadsSlowMax = 1;
    LOG_TOPIC("54252", WARN, Logger::MAINTENANCE)
        << "maintenance-slow-threads raised to "
        << opts.maintenanceThreadsSlowMax;
  }
}

}  // namespace arangodb
