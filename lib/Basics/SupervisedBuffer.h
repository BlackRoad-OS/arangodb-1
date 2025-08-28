#pragma once

#include <memory>
#include <velocypack/Buffer.h>
#include "ResourceUsage.h"

namespace arangodb::velocypack {

class SupervisedBuffer : public Buffer<uint8_t> {
 public:
  SupervisedBuffer() = delete;

  explicit SupervisedBuffer(arangodb::ResourceMonitor& monitor)
      : _usageScope(monitor) {}

  uint8_t* steal() noexcept override {
    uint8_t* ptr = Buffer<uint8_t>::steal();
<<<<<<< HEAD
    _usageScope.revert();
=======
    _usageScope.steal();
>>>>>>> 9657cfee0a117db45a33997475dad11f76bedac9
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

  arangodb::ResourceUsageScope _usageScope;
};

}  // namespace arangodb::velocypack