#include "gtest/gtest.h"
#include "Basics/ResourceUsage.h"
#include "Basics/SupervisedBuffer.h"
#include "Aql/AqlValue.h"
#include "velocypack/Builder.h"
#include <string>

using arangodb::GlobalResourceMonitor;
using arangodb::ResourceMonitor;
using arangodb::ResourceUsageScope;
using arangodb::aql::AqlValue;
using arangodb::aql::buildSupervisedAqlValue;
using arangodb::velocypack::Builder;
using arangodb::velocypack::SupervisedBuffer;
using arangodb::velocypack::Value;

/*
 * While the builder exists, the
memory its buffer uses must be counted in the query’s resource monitor.

After the builder goes out of scope, only the memory used by the AqlValue should
be accounted.

 large values force heap allocation, small values are inlined
 */

TEST(BuildSupervisedAqlValueTest, AccountsMemoryLargeAndSmallValues) {
  ResourceMonitor monitor(GlobalResourceMonitor::instance());
  ResourceUsageScope usageScope(monitor);
  SupervisedBuffer supervisedBuffer(monitor);

  // large payload to force the builder to allocate
  AqlValue largeValue;
  {
    Builder builder(supervisedBuffer);
    builder.openArray();
    builder.add(Value(std::string(1024, 'a')));
    builder.close();
    ASSERT_EQ(monitor.current(), 0);
    largeValue = buildSupervisedAqlValue(builder, usageScope);

    ASSERT_EQ(monitor.current(), largeValue.memoryUsage());
  }

  ASSERT_EQ(monitor.current(), largeValue.memoryUsage());
  largeValue.destroy();
  ASSERT_EQ(monitor.current(), 0);

  AqlValue smallValue;
  {
    Builder builder(supervisedBuffer);
    builder.openArray();
    builder.add(Value(1));
    builder.close();
    ASSERT_EQ(monitor.current(), 0);
    smallValue = buildSupervisedAqlValue(builder, usageScope);
    ASSERT_EQ(monitor.current(), 0);
  }
  ASSERT_EQ(monitor.current(), 0);
  smallValue.destroy();
  ASSERT_EQ(monitor.current(), 0);
}

TEST_F(BuildSupervisedTest, AccountsMemorySupervisedValues) {
  monitor.setMemoryLimit(1024 * 1024);

  // the builder will go out of scope at the end
  auto makeAqlValue = [this]() -> AqlValue {
    ResourceUsageScope usageScope(monitor);

    SupervisedBuffer supervisedBuffer(monitor);
    Builder builder(supervisedBuffer);
    builder.openArray();
    builder.add(Value(std::string(400, 'a')));
    builder.close();

    // only the buffer inside the builder is accounted at this moment
    std::size_t usageBefore = monitor.current();
    ASSERT_GT(usageBefore, 0);

    // as the builder is still in scope, monitor must have accounted for aql
    // value + buffer inside builder's value
    AqlValue aqlValue = buildSupervisedAqlValue(builder, usageScope);
    std::size_t usageDuring = monitor.current();
    ASSERT_GT(usageDuring, usageBefore);

    return aqlValue;
  };

  AqlValue aqlValue = makeAqlValue();

  // now that the builder is out of scope, the memory usage should be only the
  // aql value
  ASSERT_EQ(monitor.current(), aqlValue.memoryUsage());

  val.destroy();
  ASSERT_EQ(monitor.current(), 0);
}

TEST(BuildSupervisedAqlValueTest,
     ManuallyIncreaseAccountsMemoryLargeAndSmallValues) {
  ResourceMonitor monitor(GlobalResourceMonitor::instance());
  {
    ResourceUsageScope usageScope(monitor);
    AqlValue largeAqlValue;
    {
      SupervisedBuffer supervisedBuffer(monitor);
      Builder builder(supervisedBuffer);
      builder.openArray();
      builder.add(Value(std::string(2048, 'a')));
      builder.close();
      std::size_t sizeBefore = monitor.current();
      ASSERT_GT(before, 0);

      usageScope.increase(builder.size());
      largeAqlValue = buildSupervisedAqlValue(builder, usageScope);

      ASSERT_GE(monitor.current(), sizeBefore + largeAqlValue.memoryUsage());
    }

    ASSERT_EQ(monitor.current(), largeAqlValue.memoryUsage());
    largeAqlValue.destroy();
    ASSERT_EQ(monitor.current(), 0);
  }

  {
    ResourceUsageScope usageScope(monitor);
    AqlValue smallAqlValue;
    {
      SupervisedBuffer supervisedBuffer(monitor);
      Builder builder(supervisedBuffer);
      builder.openArray();
      builder.add(Value(42));
      builder.close();
      std::size_t sizeBefore = monitor.current();
      ASSERT_GE(sizeBefore, 0);

      usageScope.increase(builder.size());
      smallAqlValue = buildSupervisedAqlValue(builder, usageScope);

      ASSERT_GE(monitor.current(), beforeSize);
    }

    ASSERT_EQ(monitor.current(), smallAqlValue.memoryUsage());
    smallAqlValue.destroy();
    ASSERT_EQ(monitor.current(), 0);
  }
}
