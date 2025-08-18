#pragma once

#include "velocypack/Buffer.h"
#include "Basics/ResourceUsage.h"

namespace arangodb::velocypack {

class SupervisedBuffer : private arangodb::velocypack::Buffer<uint8_t> {
 public:
  SupervisedBuffer() = default;

  explicit SupervisedBuffer(ResourceMonitor& monitor)
      : _usageScope(std::make_unique<ResourceUsageScope>(monitor)),
        _usageScopeRaw(_usageScope.get()) {}

 private:
  void grow(ValueLength length) override {
    auto currentCapacity = this->capacity();
    velocypack::Buffer<uint8_t>::grow(length);
    auto newCapacity = this->capacity();
    if (_usageScope && newCapacity > currentCapacity) {
      _usageScope->increase(newCapacity - currentCapacity);
    }
  }

  uint8_t* steal() override {
    uint8_t* ptr = velocypack::Buffer<uint8_t>::steal();
    if (_usageScope) {  // assume it exists without checking?
      _usageScope->steal();
    }
    return ptr;
  }

  void clear() override {
    auto before = this->capacity();
    Buffer<uint8_t>::clear();
    auto after = this->capacity();
    // if before > after, means that it has released usage from the heap
    if (_usageScope && before > after) {
      _usageScope->decrease(before - after);
    }
  }

  std::unique_ptr<ResourceUsageScope> _usageScope;
  ResourceUsageScope* _usageScopeRaw{nullptr};
};

}  // namespace arangodb::velocypack