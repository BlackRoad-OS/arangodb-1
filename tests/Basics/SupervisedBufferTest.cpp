#include "gtest/gtest.h"

#include "Basics/ResourceUsage.h"
#include "Basics/SupervisedBuffer.h"

#include <velocypack/Builder.h>
#include <velocypack/Value.h>
#include <velocypack/Slice.h>

using arangodb::basics::Exception;

using arangodb::ResourceMonitor;

using arangodb::velocypack::Builder;
using arangodb::velocypack::SupervisedBuffer;
using arangodb::velocypack::Value;

TEST(SupervisedBufferTest, CapacityAccounting_GrowAndClear) {
  ResourceMonitor monitor(nullptr);
  std::size_t initial = monitor.current();

  {
    SupervisedBuffer supervisedBuffer(monitor);
    Builder builder(supervisedBuffer);

    builder.openArray();
    for (int i = 0; i < 200; ++i) {
      builder.add(Value("abcde"));
    }
    builder.close();

    ASSERT_GT(monitor.current(), initial);

    supervisedBuffer.clear();
    ASSERT_EQ(monitor.current(), initial);
  }

  ASSERT_EQ(monitor.current(), initial);
}

TEST(SupervisedBufferTest, EnforcesLimit_OnGrowth) {
  ResourceMonitor monitor(nullptr);
  monitor.setMemoryLimit(1024);  // 1 kB limit

  SupervisedBuffer supervisedBuffer(monitor);
  Builder builder(supervisedBuffer);

  builder.openArray();
  builder.add(Value(std::string(256, 'a')));
  ASSERT_LE(monitor.current(), monitor.memoryLimit());

  try {
    builder.add(Value(std::string(4096, 'b')));
    builder.close();
    FAIL() << "Expected arangodb::basics::Exception due to memory limit";
  } catch (Exception const& ex) {
    ASSERT_EQ(TRI_ERROR_RESOURCE_LIMIT, ex.code());
  }

  supervisedBuffer.clear();

  ASSERT_LE(monitor.current(), monitor.memoryLimit());
}
