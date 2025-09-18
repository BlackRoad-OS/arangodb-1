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
/// @author Julia Puget
////////////////////////////////////////////////////////////////////////////////

#pragma once

#include <memory>
#include <velocypack/Buffer.h>
#include "ResourceUsage.h"

namespace arangodb::velocypack {

class SupervisedBuffer : public Buffer<uint8_t> {
 public:
  SupervisedBuffer() = delete;

  explicit SupervisedBuffer(arangodb::ResourceMonitor& monitor)
      : _usageScope{monitor, 0} {
    // account the initial inline capacity one time (192 bytes)
    _usageScope.increase(this->capacity());
  }

  uint8_t* stealWithMemoryAccounting(ResourceUsageScope& owningScope) noexcept {
    std::size_t tracked = _usageScope.tracked();
    if (tracked == 0) {
      TRI_ASSERT(false) << "stealWithMemoryAccounting requires buffer to have "
                           "heap allocated memory";
      return nullptr;
    }
    // first add the tracked bytes to the owning scope. if this throws, do
    // nothing
    try {
      owningScope.increase(tracked);
    } catch (...) {
      return nullptr;
    }
    // steal the underlying buffer, detaches the heap allocation and resets
    // capacity to the inline value

    uint8_t* ptr = Buffer<uint8_t>::steal();
    // remove the same amount from the buffer's scope, keeping the global
    // monitor constant
    _usageScope.decrease(tracked);
    return ptr;
  }

  uint8_t* steal() noexcept override {
    TRI_ASSERT(false)
        << "raw steal() call not permitted in Supervised Buffer, please use "
           "stealWithMemoryAccounting(ResourceUsageScope& )";

    uint8_t* ptr = Buffer<uint8_t>::steal();
    _usageScope.revert();
    return ptr;
  }

 private:
  void grow(ValueLength length) override {
    auto currentCapacity = this->capacity();
    Buffer<uint8_t>::grow(length);
    auto newCapacity = this->capacity();
    if (newCapacity > currentCapacity) {
      _usageScope.increase(newCapacity - currentCapacity);
    }
  }

  void clear() noexcept override {
    auto before = this->capacity();
    Buffer<uint8_t>::clear();
    auto after = this->capacity();
    // if before > after, means that it has released usage from the heap
    if (before > after) {
      _usageScope.decrease(before - after);
    }
  }

  ResourceUsageScope _usageScope;
};

}  // namespace arangodb::velocypack
