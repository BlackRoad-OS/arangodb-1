#include "gtest/gtest.h"
#include "Basics/ResourceUsage.h"
#include "Basics/SupervisedBuffer.h"
#include "Aql/AqlValue.h"
#include <velocypack/Builder.h>
#include <string>

using arangodb::GlobalResourceMonitor;
using arangodb::ResourceMonitor;
using arangodb::ResourceUsageScope;
using arangodb::aql::AqlValue;
using arangodb::aql::buildSupervisedAqlValue;
using arangodb::basics::SupervisedBuffer;
using arangodb::velocypack::Builder;
using arangodb::velocypack::Value;

TEST(BuildSupervisedAqlValueTest,
     AccountsMemoryLargeAndSmallValuesNormalBuffer) {
  ResourceMonitor monitor(GlobalResourceMonitor::instance());

  {
    ResourceUsageScope usageScope(monitor);
    AqlValue largeValue;
    {
      Builder builder;
      builder.openArray();
      builder.add(Value(std::string(1024, 'a')));
      builder.close();

      ASSERT_EQ(monitor.current(), 0);
      largeValue = buildSupervisedAqlValue(builder, monitor);

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
      smallValue = buildSupervisedAqlValue(builder, monitor);
      ASSERT_EQ(monitor.current(), smallValue.memoryUsage());
    }
    // is the same as comparing to smallValue.memoryUsage
    ASSERT_EQ(monitor.current(), 0);
    smallValue.destroy();
    ASSERT_EQ(monitor.current(), 0);
  }
}

TEST(BuildSupervisedAqlValueTest,
     AccountsMemoryLargeAndSmallValuesSupervisedBuffer) {
  ResourceMonitor monitor(GlobalResourceMonitor::instance());

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
      largeValue = buildSupervisedAqlValue(builder, monitor);
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
      smallValue = buildSupervisedAqlValue(builder, monitor);
      ASSERT_GE(monitor.current(), smallValue.memoryUsage());
    }
    ASSERT_EQ(monitor.current(), smallValue.memoryUsage());
    smallValue.destroy();
    ASSERT_EQ(monitor.current(), 0);
  }
}

TEST(BuildSupervisedAqlValueTest,
     ManuallyIncreaseAccountsMemoryLargeAndSmallValuesSupervisedBuffer) {
  ResourceMonitor monitor(GlobalResourceMonitor::instance());

  {
    ResourceUsageScope usageScope(monitor);
    AqlValue largeValue;
    {
      SupervisedBuffer supervisedBuffer(monitor);
      Builder builder(supervisedBuffer);
      builder.openArray();
      builder.add(Value(std::string(2048, 'a')));
      builder.close();
      ASSERT_GT(monitor.current(), 0);
      std::size_t sizeBefore = builder.size();
      usageScope.increase(sizeBefore);  // pessimistic guard
      largeValue = buildSupervisedAqlValue(builder, monitor);
      ASSERT_GE(monitor.current(), sizeBefore + largeValue.memoryUsage());
    }
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
      builder.add(Value(42));
      builder.close();
      ASSERT_GT(monitor.current(), 0);
      std::size_t sizeBefore = builder.size();
      usageScope.increase(sizeBefore);
      smallValue = buildSupervisedAqlValue(builder, monitor);
      // For a small aql value, its memoryUsage() == 0; monitor >= sizeBefore
      ASSERT_GE(monitor.current(), sizeBefore);
    }
    ASSERT_EQ(monitor.current(), smallValue.memoryUsage());
    smallValue.destroy();
    ASSERT_EQ(monitor.current(), 0);
  }
}

TEST(BuildSupervisedAqlValueTest,
     ManuallyIncreaseAccountsMemoryLargeAndSmallValuesNormalBuffer) {
  ResourceMonitor monitor(GlobalResourceMonitor::instance());

  {
    ResourceUsageScope usageScope(monitor);
    AqlValue largeValue;
    {
      Builder builder;
      builder.openArray();
      builder.add(Value(std::string(2048, 'a')));
      builder.close();
      ASSERT_EQ(monitor.current(),
                0);  // it's still zero because the builder doesn't tell the
      // monitor that's increasing memory, as it doesn't have a
      // supervised buffer
      std::size_t sizeBefore = builder.size();
      usageScope.increase(sizeBefore);
      largeValue = buildSupervisedAqlValue(builder, monitor);
      // Should account builder.size() + aql value usage
      ASSERT_GE(monitor.current(), sizeBefore + largeValue.memoryUsage());
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
      builder.add(Value(42));
      builder.close();
      ASSERT_EQ(monitor.current(), 0);
      std::size_t sizeBefore = builder.size();
      usageScope.increase(sizeBefore);
      smallValue = buildSupervisedAqlValue(builder, monitor);
      // aql value memoryUsage() == 0  monitor == sizeBefore because it doesn't
      // tell the monitor to remove the memory accounted in the manual increase
      // when it leaves the scope
      ASSERT_EQ(monitor.current(), sizeBefore);
    }
    ASSERT_EQ(monitor.current(), smallValue.memoryUsage());
    smallValue.destroy();
    ASSERT_EQ(monitor.current(), 0);
  }
}

TEST(BuildSupervisedAqlValueTest, ReuseSupervisedBufferAccountsMemory) {
  ResourceMonitor monitor(GlobalResourceMonitor::instance());

  AqlValue firstValue;
  AqlValue secondValue;

  {
    SupervisedBuffer supervisedBuffer(monitor);
    Builder builder(supervisedBuffer);
    builder.openArray();
    builder.add(Value(std::string(1024, 'a')));
    builder.close();
    firstValue = buildSupervisedAqlValue(builder, monitor);
    ASSERT_GE(monitor.current(), firstValue.memoryUsage());
  }
  ASSERT_EQ(monitor.current(), firstValue.memoryUsage());

  {
    SupervisedBuffer supervisedBuffer(monitor);
    Builder builder(supervisedBuffer);
    builder.openArray();
    builder.add(Value(std::string(2048, 'b')));
    builder.close();
    secondValue = buildSupervisedAqlValue(builder, monitor);
    ASSERT_GE(monitor.current(),
              firstValue.memoryUsage() + secondValue.memoryUsage());
  }
  ASSERT_EQ(monitor.current(),
            firstValue.memoryUsage() + secondValue.memoryUsage());

  firstValue.destroy();
  secondValue.destroy();
  ASSERT_EQ(monitor.current(), 0);
}
