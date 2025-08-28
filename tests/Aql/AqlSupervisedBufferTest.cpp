#include "gtest/gtest.h"

#include "Aql/AqlValue.h"
#include "Basics/Exceptions.h"
#include "Basics/GlobalResourceMonitor.h"
#include "Basics/ResourceUsage.h"
#include "Basics/SupervisedBuffer.h"
#include <velocypack/Builder.h>
#include <string>

using namespace arangodb;
using namespace arangodb::aql;
using namespace arangodb::velocypack;

TEST(SupervisedBuferTest, AccountsMemoryLargeAndSmallValuesNormalBuffer) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor monitor{global};

  {
    ResourceUsageScope usageScope(monitor);
    AqlValue largeValue;
    {
      Builder builder;
      builder.openArray();
      builder.add(Value(std::string(1024, 'a')));
      builder.close();

      ASSERT_EQ(monitor.current(), 0);
      largeValue = AqlValue{builder.slice(), builder.size()};

      ASSERT_EQ(monitor.current(), largeValue.memoryUsage());
    }
    ASSERT_EQ(monitor.current(), largeValue.memoryUsage());
    largeValue.destroy();
    ASSERT_EQ(monitor.current(), 0);
  }

  {
    ResourceUsageScope usageScope(monitor);
    AqlValue smallValue;
    {
      Builder builder;
      builder.openArray();
      builder.add(Value(1));
      builder.close();
      ASSERT_EQ(monitor.current(), 0);
      smallValue = AqlValue{builder.slice(), builder.size()};
      ASSERT_EQ(monitor.current(), smallValue.memoryUsage());
    }
    // is the same as comparing to smallValue.memoryUsage
    ASSERT_EQ(monitor.current(), 0);
    smallValue.destroy();
    ASSERT_EQ(monitor.current(), 0);
  }
}

TEST(SupervisedBuferTest, AccountsMemoryLargeAndSmallValuesSupervisedBuffer) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor monitor{global};

  {
    ResourceUsageScope usageScope(monitor);
    AqlValue largeValue;
    {
      SupervisedBuffer supervisedBuffer(monitor);
      Builder builder(supervisedBuffer);
      builder.openArray();
      builder.add(Value(std::string(1024, 'a')));
      builder.close();

      ASSERT_GT(monitor.current(), 0);
      largeValue = AqlValue{builder.slice(), builder.size()};
      // While builder exists, monitor >= aql value usage (buffer + aql value)
      ASSERT_GE(monitor.current(), largeValue.memoryUsage());
    }
    // now monitor is only the aql value usage
    ASSERT_EQ(monitor.current(), largeValue.memoryUsage());
    largeValue.destroy();
    ASSERT_EQ(monitor.current(), 0);
  }

  {
    ResourceUsageScope usageScope(monitor);
    AqlValue smallValue;
    {
      SupervisedBuffer supervisedBuffer(monitor);
      Builder builder(supervisedBuffer);
      builder.openArray();
      builder.add(Value(1));
      builder.close();
      ASSERT_GT(monitor.current(), 0);
      smallValue = AqlValue{builder.slice(), builder.size()};
      ASSERT_GE(monitor.current(), smallValue.memoryUsage());
    }
    ASSERT_EQ(monitor.current(), smallValue.memoryUsage());
    smallValue.destroy();
    ASSERT_EQ(monitor.current(), 0);
  }
}

TEST(SupervisedBuferTest,
     ManuallyIncreaseAccountsMemoryLargeAndSmallValuesSupervisedBuffer) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor monitor{global};

  {
    ResourceUsageScope usageScope(monitor);
    AqlValue largeValue;
    std::size_t sizeBeforeLocal = 0;
    std::size_t valueSizeLocal = 0;
    {
      SupervisedBuffer supervisedBuffer(monitor);
      Builder builder(supervisedBuffer);
      builder.openArray();
      builder.add(Value(std::string(2048, 'a')));
      builder.close();
      ASSERT_GT(monitor.current(), 0);

      std::size_t monitorBefore = monitor.current();
      std::size_t sizeBefore = builder.size();
      usageScope.increase(sizeBefore);
      ASSERT_EQ(monitor.current(), monitorBefore + sizeBefore);

      sizeBeforeLocal = sizeBefore;
      largeValue = AqlValue{builder.slice(), builder.size()};
      valueSizeLocal = largeValue.memoryUsage();
      ASSERT_GE(monitor.current(), sizeBefore + largeValue.memoryUsage());
    }
    ASSERT_GE(monitor.current(), sizeBeforeLocal + valueSizeLocal);
    largeValue.destroy();
    ASSERT_EQ(monitor.current(), 0);
  }

  {
    ResourceUsageScope usageScope(monitor);
    AqlValue smallValue;
    std::size_t sizeBeforeLocal = 0;
    std::size_t valueSizeLocal = 0;
    {
      SupervisedBuffer supervisedBuffer(monitor);
      Builder builder(supervisedBuffer);
      builder.openArray();
      builder.add(Value(42));
      builder.close();
      ASSERT_GT(monitor.current(), 0);

      std::size_t monitorBefore = monitor.current();
      std::size_t sizeBefore = builder.size();
      usageScope.increase(sizeBefore);
      ASSERT_EQ(monitor.current(), monitorBefore + sizeBefore);

      sizeBeforeLocal = sizeBefore;
      smallValue = AqlValue{builder.slice(), builder.size()};
      valueSizeLocal = smallValue.memoryUsage();
      ASSERT_GE(monitor.current(), sizeBefore + smallValue.memoryUsage());
    }
    ASSERT_GE(monitor.current(), sizeBeforeLocal + valueSizeLocal);
    smallValue.destroy();
    ASSERT_EQ(monitor.current(), 0);
  }
}

TEST(SupervisedBuferTest,
     ManuallyIncreaseAccountsMemoryLargeAndSmallValuesNormalBuffer) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor monitor{global};

  {
    ResourceUsageScope usageScope(monitor);
    AqlValue largeValue;
    std::size_t sizeBeforeLocal = 0;
    std::size_t valueSizeLocal = 0;
    {
      Builder builder;
      builder.openArray();
      builder.add(Value(std::string(2048, 'a')));
      builder.close();
      ASSERT_EQ(monitor.current(), 0);

      std::size_t monitorBefore = monitor.current();
      std::size_t sizeBefore = builder.size();
      usageScope.increase(sizeBefore);
      ASSERT_EQ(monitor.current(), monitorBefore + sizeBefore);

      sizeBeforeLocal = sizeBefore;
      largeValue = AqlValue{builder.slice(), builder.size()};
      valueSizeLocal = largeValue.memoryUsage();
      ASSERT_EQ(monitor.current(), sizeBefore + largeValue.memoryUsage());
    }
    ASSERT_EQ(monitor.current(), sizeBeforeLocal + valueSizeLocal);
    largeValue.destroy();
    ASSERT_EQ(monitor.current(), 0);
  }

  {
    ResourceUsageScope usageScope(monitor);
    AqlValue smallValue;
    std::size_t sizeBeforeLocal = 0;
    std::size_t valueSizeLocal = 0;
    {
      Builder builder;
      builder.openArray();
      builder.add(Value(42));
      builder.close();
      ASSERT_EQ(monitor.current(), 0);

      std::size_t preMonitor = monitor.current();
      std::size_t sizeBefore = builder.size();
      usageScope.increase(sizeBefore);
      ASSERT_EQ(monitor.current(), preMonitor + sizeBefore);

      sizeBeforeLocal = sizeBefore;
      smallValue = AqlValue{builder.slice(), builder.size()};
      valueSizeLocal = smallValue.memoryUsage();
      ASSERT_EQ(monitor.current(), sizeBefore + smallValue.memoryUsage());
    }
    ASSERT_EQ(monitor.current(), sizeBeforeLocal + valueSizeLocal);
    smallValue.destroy();
    ASSERT_EQ(monitor.current(), 0);
  }
}

TEST(SupervisedBuferTest, ReuseSupervisedBufferAccountsMemory) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor monitor{global};

  AqlValue firstValue;
  AqlValue secondValue;

  {
    SupervisedBuffer supervisedBuffer(monitor);
    Builder builder(supervisedBuffer);
    builder.openArray();
    builder.add(Value(std::string(1024, 'a')));
    builder.close();
    firstValue = AqlValue{builder.slice(), builder.size()};
    ASSERT_GE(monitor.current(), firstValue.memoryUsage());
  }
  ASSERT_EQ(monitor.current(), firstValue.memoryUsage());

  {
    SupervisedBuffer supervisedBuffer(monitor);
    Builder builder(supervisedBuffer);
    builder.openArray();
    builder.add(Value(std::string(2048, 'b')));
    builder.close();
    secondValue = AqlValue{builder.slice(), builder.size()};
    ASSERT_GE(monitor.current(),
              firstValue.memoryUsage() + secondValue.memoryUsage());
  }
  ASSERT_EQ(monitor.current(),
            firstValue.memoryUsage() + secondValue.memoryUsage());

  firstValue.destroy();
  secondValue.destroy();
  ASSERT_EQ(monitor.current(), 0);
}

TEST(SupervisedBuferTest, SupervisedBuilderGrowthAndRecycle) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor monitor{global};

  {
    ResourceUsageScope usageScope(monitor);
    SupervisedBuffer supervisedBuffer(monitor);
    Builder builder(supervisedBuffer);

    // memory should be low >= size here
    builder.openArray();
    builder.add(Value(1));
    builder.add(Value(2));
    builder.add(Value(3));
    builder.close();
    AqlValue smallValue = AqlValue{builder.slice(), builder.size()};
    std::size_t memory1 = monitor.current();
    ASSERT_GE(memory1, builder.size());

    // now we force a growth of the buffer
    builder.clear();
    builder.openArray();
    for (int i = 0; i < 200; ++i) {
      builder.add(Value(std::string(1024, 'a')));
    }
    builder.close();
    AqlValue largeValue = AqlValue{builder.slice(), builder.size()};
    std::size_t memory2 = monitor.current();
    ASSERT_GT(memory2, memory1);
    ASSERT_GE(memory2, builder.size());

    // recycle the buffer, the memory should remain high even though
    // builder.size() becomes 0 because of capacity.
    builder.clear();
    AqlValue clearedValue = AqlValue{builder.slice(), builder.size()};
    std::size_t memory3 = monitor.current();
    ASSERT_EQ(memory3, memory2);

    clearedValue.destroy();
    largeValue.destroy();
    smallValue.destroy();
  }
  ASSERT_EQ(monitor.current(), 0);
}

TEST(SupervisedBuferTest, DetailedBufferResizeAndRecycle) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor monitor{global};

  {
    ResourceUsageScope usageScope(monitor);
    SupervisedBuffer supervisedBuffer(monitor);
    Builder builder(supervisedBuffer);

    builder.openArray();
    for (int i = 0; i < 5; ++i) {
      builder.add(Value(i));
    }
    builder.close();
    std::size_t memory1 = monitor.current();
    ASSERT_GE(memory1, builder.size());
    builder.clear();
    builder.openArray();
    for (int i = 0; i < 100; ++i) {
      builder.add(Value(std::string(256, 'a')));
    }
    builder.close();
    std::size_t memory2 = monitor.current();
    ASSERT_GE(memory2, builder.size());
    ASSERT_GT(memory2, memory1);

    ASSERT_GE(monitor.current(), builder.size());

    builder.clear();
    builder.openArray();
    builder.close();
    std::size_t memory3 = monitor.current();
    ASSERT_GE(memory3, builder.size());
    ASSERT_EQ(memory3, memory2);
  }
  ASSERT_EQ(monitor.current(), 0);
}
