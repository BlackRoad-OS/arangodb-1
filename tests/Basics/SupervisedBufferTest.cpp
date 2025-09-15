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

TEST(SupervisedbufferTest, AccountsMemoryLargeAndSmallValuesNormalBuffer) {
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
      monitor.increaseMemoryUsage(largeValue.memoryUsage());

      ASSERT_EQ(monitor.current(), largeValue.memoryUsage());
    }
    ASSERT_EQ(monitor.current(), largeValue.memoryUsage());

    monitor.decreaseMemoryUsage(largeValue.memoryUsage());
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
      // memoryUsage for small values  is zero
      // because they fit in the AqlValue's inline buffer
      monitor.increaseMemoryUsage(smallValue.memoryUsage());
      ASSERT_EQ(monitor.current(), smallValue.memoryUsage());
    }
    // is the same as comparing to smallValue.memoryUsage
    ASSERT_EQ(monitor.current(), 0);

    monitor.decreaseMemoryUsage(smallValue.memoryUsage());
    smallValue.destroy();
    ASSERT_EQ(monitor.current(), 0);
  }
}

TEST(SupervisedbufferTest, AccountsMemoryLargeAndSmallValuesSupervisedBuffer) {
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
      // the buffer has already increased the monitor for its
      // capacity, this call adds the AqlValue footprint on top.
      monitor.increaseMemoryUsage(largeValue.memoryUsage());
      // While builder exists, monitor >= aql value usage (buffer + aql value)
      ASSERT_GE(monitor.current(), largeValue.memoryUsage());
    }
    // now monitor is only the aql value usage
    ASSERT_EQ(monitor.current(), largeValue.memoryUsage());

    monitor.decreaseMemoryUsage(largeValue.memoryUsage());
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
      // account small value on the monitor
      monitor.increaseMemoryUsage(smallValue.memoryUsage());
      ASSERT_GE(monitor.current(), smallValue.memoryUsage());
    }
    ASSERT_EQ(monitor.current(), smallValue.memoryUsage());
    monitor.decreaseMemoryUsage(smallValue.memoryUsage());
    smallValue.destroy();
    ASSERT_EQ(monitor.current(), 0);
  }
}

TEST(SupervisedbufferTest,
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
      // account the value's memory on top of manual buffer accounting
      monitor.increaseMemoryUsage(valueSizeLocal);
      ASSERT_GE(monitor.current(), sizeBefore + largeValue.memoryUsage());
    }
    ASSERT_GE(monitor.current(), sizeBeforeLocal + valueSizeLocal);
    // drop our manual accounting for the value before destroying it
    monitor.decreaseMemoryUsage(valueSizeLocal);
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
      monitor.increaseMemoryUsage(valueSizeLocal);
      ASSERT_GE(monitor.current(), sizeBefore + smallValue.memoryUsage());
    }
    ASSERT_GE(monitor.current(), sizeBeforeLocal + valueSizeLocal);
    monitor.decreaseMemoryUsage(valueSizeLocal);
    smallValue.destroy();
    ASSERT_EQ(monitor.current(), 0);
  }
}

TEST(SupervisedbufferTest,
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
      // account the value's memory on top of the manual buffer
      monitor.increaseMemoryUsage(valueSizeLocal);
      ASSERT_EQ(monitor.current(), sizeBefore + largeValue.memoryUsage());
    }
    ASSERT_EQ(monitor.current(), sizeBeforeLocal + valueSizeLocal);
    monitor.decreaseMemoryUsage(valueSizeLocal);
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
      monitor.increaseMemoryUsage(valueSizeLocal);
      ASSERT_EQ(monitor.current(), sizeBefore + smallValue.memoryUsage());
    }
    ASSERT_EQ(monitor.current(), sizeBeforeLocal + valueSizeLocal);
    monitor.decreaseMemoryUsage(valueSizeLocal);
    smallValue.destroy();
    ASSERT_EQ(monitor.current(), 0);
  }
}

TEST(SupervisedbufferTest, ReuseSupervisedBufferAccountsMemory) {
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

    monitor.increaseMemoryUsage(firstValue.memoryUsage());
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

    monitor.increaseMemoryUsage(secondValue.memoryUsage());
    ASSERT_GE(monitor.current(),
              firstValue.memoryUsage() + secondValue.memoryUsage());
  }
  ASSERT_EQ(monitor.current(),
            firstValue.memoryUsage() + secondValue.memoryUsage());

  // drop our manual accounting for both values before destroying them
  monitor.decreaseMemoryUsage(firstValue.memoryUsage());
  monitor.decreaseMemoryUsage(secondValue.memoryUsage());
  firstValue.destroy();
  secondValue.destroy();
  ASSERT_EQ(monitor.current(), 0);
}

TEST(SupervisedbufferTest, SupervisedBuilderGrowthAndRecycle) {
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
    // account the small value on the monitor. smallValue.memoryUsage()
    // may be zero, in which case this has no effect.
    monitor.increaseMemoryUsage(smallValue.memoryUsage());
    std::size_t memory1 = monitor.current();
    ASSERT_GE(memory1, builder.size());

    builder.clear();
    builder.openArray();
    for (int i = 0; i < 200; ++i) {
      builder.add(Value(std::string(1024, 'a')));
    }
    builder.close();
    AqlValue largeValue = AqlValue{builder.slice(), builder.size()};
    monitor.increaseMemoryUsage(largeValue.memoryUsage());
    std::size_t memory2 = monitor.current();
    ASSERT_GT(memory2, memory1);
    ASSERT_GE(memory2, builder.size());

    // recycle the buffer, the memory should remain high even though
    // builder.size() becomes 0 because of capacity.
    builder.clear();
    AqlValue clearedValue = AqlValue{builder.slice(), builder.size()};
    monitor.increaseMemoryUsage(clearedValue.memoryUsage());
    std::size_t memory3 = monitor.current();
    ASSERT_EQ(memory3, memory2);

    // drop accounting in reverse order of creation
    monitor.decreaseMemoryUsage(clearedValue.memoryUsage());
    clearedValue.destroy();
    monitor.decreaseMemoryUsage(largeValue.memoryUsage());
    largeValue.destroy();
    monitor.decreaseMemoryUsage(smallValue.memoryUsage());
    smallValue.destroy();
  }
  ASSERT_EQ(monitor.current(), 0);
}

<<<<<<< HEAD
TEST(SupervisedbufferTest, DetailedBufferResizeAndRecycle) {
=======
TEST(SupervisedBufferTest, DetailedBufferResizeAndRecycle) {
>>>>>>> 57d55981f907d7fa71c3dc281e847b130db6679b
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

TEST(SupervisedBufferTest, AccountCapacityGrowAndClear) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor monitor(global);
  ASSERT_EQ(monitor.current(), 0);

  {
    SupervisedBuffer supervisedBuffer(monitor);
    Builder builder(supervisedBuffer);
    builder.openArray();
    for (int i = 0; i < 200; ++i) {
      builder.add(Value("abcde"));
    }
    builder.close();

    // current is capacity, so it must be >= byte size
    ASSERT_GE(monitor.current(), builder.size());
    // recycle but don’t shrink
    std::size_t keep = monitor.current();
    builder.clear();
    ASSERT_EQ(monitor.current(), keep);
  }

  ASSERT_EQ(monitor.current(), 0);
}

TEST(SupervisedBufferTest, EnforceMemoryLimitOnGrowth) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor monitor(global);
  monitor.memoryLimit(1024);

  {
    SupervisedBuffer supervisedBuffer(monitor);
    Builder builder(supervisedBuffer);
    builder.openArray();
    bool threw = false;
    try {
      for (int i = 0; i < 4096; ++i) {
        builder.add(Value("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"));  // 32 bytes
      }
    } catch (arangodb::basics::Exception const& ex) {
      threw = true;
      EXPECT_EQ(TRI_ERROR_RESOURCE_LIMIT, ex.code());
    }
    EXPECT_TRUE(threw);
  }
  ASSERT_EQ(monitor.current(), 0);
}

TEST(SupervisedBufferTest, MultipleGrowsAndRecycle) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor monitor(global);
  ASSERT_EQ(monitor.current(), 0);

  {
    SupervisedBuffer supervisedBuffer(monitor);
    Builder builder(supervisedBuffer);
    builder.openArray();

    // no growth expected yet
    std::size_t lastCapacity = supervisedBuffer.capacity();
    std::size_t lastMonitorCurrent = monitor.current();
    for (int i = 0; i < 8; ++i) {
      builder.add(Value("ab"));
      ASSERT_GE(monitor.current(), builder.size());
    }

    // Add more items until the buffer grows twice
    int growths = 0;
    for (int i = 0; i < 512 && growths < 2; ++i) {
      builder.add(Value("abcdefghijklmnopqrstuvwxyz"));
      if (supervisedBuffer.capacity() > lastCapacity) {
        ASSERT_GT(monitor.current(), lastMonitorCurrent);  // monitor increased
        ASSERT_GE(monitor.current(), builder.size());
        lastCapacity = supervisedBuffer.capacity();
        lastMonitorCurrent = monitor.current();
        ++growths;
      } else {
        ASSERT_GE(monitor.current(), builder.size());
      }
    }
    ASSERT_GE(growths, 2);
    builder.close();
    ASSERT_GE(monitor.current(), builder.size());

    // Recycle the buffer, memory doesn't decrease
    auto maintainedMonitorCurrent = monitor.current();
    builder.clear();
    ASSERT_EQ(monitor.current(), maintainedMonitorCurrent);

    // Append items but capacity must remain the same
    builder.openArray();
    for (int i = 0; i < 16; ++i) {
      builder.add(Value("abcde"));
      ASSERT_GE(monitor.current(), builder.size());
      ASSERT_EQ(monitor.current(), maintainedMonitorCurrent);
    }
    builder.close();
    ASSERT_EQ(monitor.current(), maintainedMonitorCurrent);
  }

  ASSERT_EQ(monitor.current(), 0);
}