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

  uint8_t* stealWithMemoryAccounting(ResourceUsageScope& owningScope) {
    std::size_t tracked = 0;
    // the buffer's usage scope is gonna account for 0 bytes now and give the
    // value it accounted for to the owning scope, so the amount of memory that
    // the buffer allocated which was accounted by its scope is now gonna be
    // accounted by the owning scope. If it throws when we increase the owning
    // scope, we don't need to increase _usageScope again, because decrease
    // didn't happen
    try {
      tracked = _usageScope.tracked();
      owningScope.increase(tracked);
      _usageScope.decrease(tracked);
    } catch (...) {
      throw;
    }
    // steal the underlying buffer, detaches the heap allocation and resets
    // capacity to the inline value
    uint8_t* ptr = Buffer<uint8_t>::steal();

    // maintain the _local value that the buffer has now after stealing (192
    // bytes)
    _usageScope.increase(this->capacity());
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
