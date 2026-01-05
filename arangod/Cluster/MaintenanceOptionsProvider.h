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

#pragma once

#include "ApplicationFeatures/OptionsProvider.h"
#include "MaintenanceOptions.h"
#include <memory>

namespace arangodb::options {
class ProgramOptions;
}

namespace arangodb {

/// @brief Declares and validates program options for Maintenance
/// Separates option handling from feature business logic
struct MaintenanceOptionsProvider : OptionsProvider<MaintenanceOptions> {
  MaintenanceOptionsProvider() = default;

  /// @brief Declare all program options, binding them to the options struct
  void declareOptions(std::shared_ptr<options::ProgramOptions> opts,
                      MaintenanceOptions& options) override;

  /// @brief Validate and transform options after parsing
  void validateOptions(std::shared_ptr<options::ProgramOptions> opts,
                       MaintenanceOptions& options) override;
};

}  // namespace arangodb
