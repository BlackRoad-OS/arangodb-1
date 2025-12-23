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
////////////////////////////////////////////////////////////////////////////////

#include "AgencyOptionsProvider.h"

#include "Basics/application-exit.h"
#include "Endpoint/Endpoint.h"
#include "Cluster/ServerState.h"
#include "Logger/Logger.h"
#include "Logger/LogMacros.h"
#include "ProgramOptions/Parameters.h"
#include "ProgramOptions/ProgramOptions.h"

#include <limits>

namespace arangodb {

using namespace arangodb::options;

void AgencyOptionsProvider::declareOptions(
    std::shared_ptr<ProgramOptions> options, AgencyOptions& opts) {
  options->addSection("agency", "agency");

  options->addOption("--agency.activate", "Activate the Agency.",
                     new BooleanParameter(&opts.activated),
                     arangodb::options::makeFlags(
                         arangodb::options::Flags::DefaultNoComponents,
                         arangodb::options::Flags::OnAgent));

  options->addOption("--agency.size", "The number of Agents.",
                     new UInt64Parameter(&opts.size),
                     arangodb::options::makeFlags(
                         arangodb::options::Flags::DefaultNoComponents,
                         arangodb::options::Flags::OnAgent));

  options
      ->addOption("--agency.pool-size", "The number of Agents in the pool.",
                  new UInt64Parameter(&opts.poolSize),
                  arangodb::options::makeFlags(
                      arangodb::options::Flags::Uncommon,
                      arangodb::options::Flags::DefaultNoComponents,
                      arangodb::options::Flags::OnAgent))
      .setDeprecatedIn(31100);

  options->addOption(
      "--agency.election-timeout-min",
      "The minimum timeout before an Agent calls for a new election (in "
      "seconds).",
      new DoubleParameter(&opts.minElectionTimeout, /*base*/ 1.0,
                          /*minValue*/ 0.0,
                          /*maxValue*/ std::numeric_limits<double>::max(),
                          /*minInclusive*/ false),
      arangodb::options::makeFlags(
          arangodb::options::Flags::DefaultNoComponents,
          arangodb::options::Flags::OnAgent));

  options->addOption("--agency.election-timeout-max",
                     "The maximum timeout before an Agent calls for a new "
                     "election (in seconds).",
                     new DoubleParameter(&opts.maxElectionTimeout),
                     arangodb::options::makeFlags(
                         arangodb::options::Flags::DefaultNoComponents,
                         arangodb::options::Flags::OnAgent));

  options->addOption(
      "--agency.endpoint", "The Agency endpoints.",
      new VectorParameter<StringParameter>(&opts.agencyEndpoints),
      arangodb::options::makeFlags(
          arangodb::options::Flags::DefaultNoComponents,
          arangodb::options::Flags::OnAgent));

  options->addOption("--agency.my-address",
                     "Which address to advertise to the outside.",
                     new StringParameter(&opts.agencyMyAddress),
                     arangodb::options::makeFlags(
                         arangodb::options::Flags::DefaultNoComponents,
                         arangodb::options::Flags::OnAgent));

  options->addOption("--agency.supervision",
                     "Perform ArangoDB cluster supervision.",
                     new BooleanParameter(&opts.supervision),
                     arangodb::options::makeFlags(
                         arangodb::options::Flags::DefaultNoComponents,
                         arangodb::options::Flags::OnAgent));

  options->addOption("--agency.supervision-frequency",
                     "The ArangoDB cluster supervision frequency (in seconds).",
                     new DoubleParameter(&opts.supervisionFrequency),
                     arangodb::options::makeFlags(
                         arangodb::options::Flags::DefaultNoComponents,
                         arangodb::options::Flags::OnAgent));

  options
      ->addOption("--agency.supervision-grace-period",
                  "The supervision time after which a server is considered to "
                  "have failed (in seconds).",
                  new DoubleParameter(&opts.supervisionGracePeriod),
                  arangodb::options::makeFlags(
                      arangodb::options::Flags::DefaultNoComponents,
                      arangodb::options::Flags::OnAgent))
      .setLongDescription(R"(A value of `10` seconds is recommended for regular
cluster deployments.)");

  options->addOption("--agency.supervision-ok-threshold",
                     "The supervision time after which a server is considered "
                     "to be bad (in seconds).",
                     new DoubleParameter(&opts.supervisionOkThreshold),
                     arangodb::options::makeFlags(
                         arangodb::options::Flags::DefaultNoComponents,
                         arangodb::options::Flags::OnAgent));

  options
      ->addOption(
          "--agency.supervision-expired-servers-grace-period",
          "The supervision time after which a server is removed "
          "from the agency if it does no longer send heartbeats "
          "(in seconds).",
          new DoubleParameter(&opts.supervisionExpiredServersGracePeriod),
          arangodb::options::makeFlags(
              arangodb::options::Flags::DefaultNoComponents,
              arangodb::options::Flags::OnAgent))
      .setIntroducedIn(31204);

  options
      ->addOption("--agency.supervision-delay-add-follower",
                  "The delay in supervision, before an AddFollower job is "
                  "executed (in seconds).",
                  new UInt64Parameter(&opts.supervisionDelayAddFollower),
                  arangodb::options::makeFlags(
                      arangodb::options::Flags::DefaultNoComponents,
                      arangodb::options::Flags::OnAgent))
      .setIntroducedIn(30906)
      .setIntroducedIn(31002);

  options
      ->addOption("--agency.supervision-delay-failed-follower",
                  "The delay in supervision, before a FailedFollower job is "
                  "executed (in seconds).",
                  new UInt64Parameter(&opts.supervisionDelayFailedFollower),
                  arangodb::options::makeFlags(
                      arangodb::options::Flags::DefaultNoComponents,
                      arangodb::options::Flags::OnAgent))
      .setIntroducedIn(30906)
      .setIntroducedIn(31002);

  options
      ->addOption("--agency.supervision-failed-leader-adds-follower",
                  "Flag indicating whether or not the FailedLeader job adds a "
                  "new follower.",
                  new BooleanParameter(&opts.failedLeaderAddsFollower),
                  arangodb::options::makeFlags(
                      arangodb::options::Flags::DefaultNoComponents,
                      arangodb::options::Flags::OnAgent))
      .setIntroducedIn(30907)
      .setIntroducedIn(31002);

  options->addOption("--agency.compaction-step-size",
                     "The step size between state machine compactions.",
                     new UInt64Parameter(&opts.compactionStepSize),
                     arangodb::options::makeFlags(
                         arangodb::options::Flags::DefaultNoComponents,
                         arangodb::options::Flags::Uncommon,
                         arangodb::options::Flags::OnAgent));

  options->addOption("--agency.compaction-keep-size",
                     "Keep as many Agency log entries before compaction point.",
                     new UInt64Parameter(&opts.compactionKeepSize),
                     arangodb::options::makeFlags(
                         arangodb::options::Flags::DefaultNoComponents,
                         arangodb::options::Flags::OnAgent));

  options->addOption("--agency.wait-for-sync",
                     "Wait for hard disk syncs on every persistence call "
                     "(required in production).",
                     new BooleanParameter(&opts.waitForSync),
                     arangodb::options::makeFlags(
                         arangodb::options::Flags::DefaultNoComponents,
                         arangodb::options::Flags::Uncommon,
                         arangodb::options::Flags::OnAgent));

  options->addOption(
      "--agency.max-append-size",
      "The maximum size of appendEntries document (number of log entries).",
      new UInt64Parameter(&opts.maxAppendSize),
      arangodb::options::makeFlags(
          arangodb::options::Flags::DefaultNoComponents,
          arangodb::options::Flags::Uncommon,
          arangodb::options::Flags::OnAgent));

  options->addOption("--agency.disaster-recovery-id",
                     "Specify the ID for this agent. WARNING: This is a "
                     "dangerous option, for disaster recover only!",
                     new StringParameter(&opts.recoveryId),
                     arangodb::options::makeFlags(
                         arangodb::options::Flags::DefaultNoComponents,
                         arangodb::options::Flags::Uncommon,
                         arangodb::options::Flags::OnAgent));
}

void AgencyOptionsProvider::validateOptions(
    std::shared_ptr<ProgramOptions> options, AgencyOptions& opts) {
  ProgramOptions::ProcessingResult const& result = options->processingResult();

  if (result.touched("agency.size")) {
    if (opts.size < 1) {
      LOG_TOPIC("98510", FATAL, Logger::AGENCY)
          << "agency must have size greater 0";
      FATAL_ERROR_EXIT();
    }
  } else {
    opts.size = 1;
  }

  if (result.touched("agency.pool-size") && opts.poolSize != opts.size) {
    LOG_TOPIC("af108", FATAL, Logger::AGENCY)
        << "agency pool size is deprecated and is not expected to be set";
    FATAL_ERROR_EXIT();
  }
  opts.poolSize = opts.size;

  if (opts.size % 2 == 0) {
    LOG_TOPIC("0eab5", FATAL, Logger::AGENCY)
        << "AGENCY: agency must have odd number of members";
    FATAL_ERROR_EXIT();
  }

  if (opts.minElectionTimeout < 0.15) {
    LOG_TOPIC("0cce9", WARN, Logger::AGENCY)
        << "very short agency.election-timeout-min!";
  }

  if (opts.maxElectionTimeout <= opts.minElectionTimeout) {
    LOG_TOPIC("62fc3", FATAL, Logger::AGENCY)
        << "agency.election-timeout-max must not be shorter than or"
        << "equal to agency.election-timeout-min.";
    FATAL_ERROR_EXIT();
  }

  if (opts.maxElectionTimeout <= 2. * opts.minElectionTimeout) {
    LOG_TOPIC("99f84", WARN, Logger::AGENCY)
        << "agency.election-timeout-max should probably be chosen longer!";
  }

  if (opts.compactionKeepSize == 0) {
    LOG_TOPIC("ca485", WARN, Logger::AGENCY)
        << "agency.compaction-keep-size must not be 0, set to 50000";
    opts.compactionKeepSize = 50000;
  }

  if (!opts.agencyMyAddress.empty()) {
    std::string const unified = Endpoint::unifiedForm(opts.agencyMyAddress);

    if (unified.empty()) {
      LOG_TOPIC("4faa0", FATAL, Logger::AGENCY)
          << "invalid endpoint '" << opts.agencyMyAddress
          << "' specified for --agency.my-address";
      FATAL_ERROR_EXIT();
    }

    std::string fallback = unified;
    auto pos = fallback.find("://");
    if (pos != std::string::npos) {
      fallback = fallback.substr(pos + 3);
    }
    pos = fallback.rfind(':');
    if (pos != std::string::npos) {
      fallback.resize(pos);
    }
    auto ss = ServerState::instance();
    ss->findHost(fallback);
  }

  if (result.touched("agency.supervision")) {
    opts.supervisionTouched = true;
  }
}

}  // namespace arangodb
