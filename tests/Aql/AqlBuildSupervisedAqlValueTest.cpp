#include "gtest/gtest.h"
#include "Basics/ResourceUsage.h"
#include "Basics/SupervisedBuffer.h"
#include "Aql/AqlValue.h"
#include "velocypack/Builder.h"
#include <string>

using arangodb::ResourceMonitor;
using arangodb::ResourceUsageScope;
using arangodb::aql::AqlValue;
using arangodb::aql::buildSupervisedAqlValue;
using arangodb::velocypack::Builder;
using arangodb::velocypack::Value;

/*
 * While the builder exists, the
memory its buffer uses must be counted in the query’s resource monitor.

After the builder goes out of scope, only the memory used by the AqlValue should
be accounted.
 */

TEST(BuildSupervisedAqlValueTest, TracksLargeAndSmallValues) {
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