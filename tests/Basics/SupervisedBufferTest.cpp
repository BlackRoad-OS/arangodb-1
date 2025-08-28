#include "gtest/gtest.h"

#include "Basics/Exceptions.h"
#include "Basics/GlobalResourceMonitor.h"
#include "Basics/ResourceUsage.h"
#include "Basics/SupervisedBuffer.h"

#include <velocypack/Builder.h>
#include <velocypack/Value.h>

using namespace arangodb;
using namespace arangodb::velocypack;

using arangodb::ResourceMonitor;

TEST(SupervisedBufferTest, CapacityAccounting_GrowAndClear) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor monitor(global);
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

    builder.clear();
    ASSERT_EQ(monitor.current(), initial);
  }

  ASSERT_EQ(monitor.current(), initial);
}

TEST(SupervisedBufferTest, EnforcesLimit_OnGrowth) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor monitor(global);
  monitor.memoryLimit(1024);  // 1 kB limit

  SupervisedBuffer supervisedBuffer(monitor);
  Builder builder(supervisedBuffer);

  builder.openArray();
  builder.add(Value(std::string(256, 'a')));
  ASSERT_LE(monitor.current(), monitor.memoryLimit());

  try {
    builder.add(Value(std::string(4096, 'b')));
    builder.close();
    FAIL() << "Expected arangodb::basics::Exception due to memory limit";
  } catch (basics::Exception const& ex) {
    ASSERT_EQ(TRI_ERROR_RESOURCE_LIMIT, ex.code());
  }

  builder.clear();

  ASSERT_LE(monitor.current(), monitor.memoryLimit());
}

TEST(SupervisedBufferTest, MemoryLimitExpectThrow) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor monitor(global);
  monitor.memoryLimit(1024);
  EXPECT_THROW(
      {
        SupervisedBuffer supervisedBuffer(monitor);
        Builder builder(supervisedBuffer);
        builder.openArray();
        builder.add(Value(std::string(2000, 'a')));
        builder.close();
      },
      std::exception);
  monitor.clear();
}
