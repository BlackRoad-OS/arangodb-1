#include "Basics/ResourceMonitor.h"
#include "SupervisedBuffer.h"
#include "velocypack/Builder.h"

TEST(SupervisedBufferTest, CapacityAccounting) {
  arangodb::ResourceMonitor monitor(nullptr);
  size_t initialUsage = monitor.current();

  {
    SupervisedBuffer buf(monitor);
    velocypack::Builder builder(&buf);
    builder.openArray();
    for (int i = 0; i < 200; ++i) {
      builder.add(VPackValue("abcde"));
    }
    builder.close();
    ASSERT_GT(monitor.current(), initialUsage);
    buf.clear();
    ASSERT_EQ(monitor.current(), initialUsage);
  }
}