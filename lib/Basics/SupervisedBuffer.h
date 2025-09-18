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
    _usageScope.increase(this->capacity());
  }

  uint8_t* stealWithMemoryAccounting(ResourceUsageScope& owningScope) noexcept {
    std::size_t tracked = _usageScope.tracked();
    if (tracked == 0) {
      TRI_ASSERT(false) << "stealWithMemoryAccounting requires buffer to have "
                           "heap allocated memory";
      return nullptr;
    }
    try {
      owningScope.increase(tracked);  // may throw on limit
    } catch (...) {
      return nullptr;
    }
    _usageScope.revert();
    uint8_t* ptr = Buffer<uint8_t>::steal();
    // _usageScope.increase(this->capacity());
    return ptr;
  }

  uint8_t* steal() noexcept override {
    TRI_ASSERT(false)
        << "raw steal() call not permitted in Supervised Buffer, please use "
           "stealWithMemoryAccounting(ResourceUsageScope& )";
    /*
    uint8_t* ptr = Buffer<uint8_t>::steal();
    _usageScope.revert();
    return ptr;
*/
    return nullptr;  // signal error to never leak unaccount
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
