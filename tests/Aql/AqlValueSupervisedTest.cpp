#include "gtest/gtest.h"

#include "Aql/AqlValue.h"
#include "Basics/GlobalResourceMonitor.h"
#include "Basics/ResourceUsage.h"
#include "Basics/SupervisedBuffer.h"

#include <velocypack/Builder.h>
#include <velocypack/Value.h>
#include <velocypack/Slice.h>

using namespace arangodb;
using namespace arangodb::aql;
using namespace arangodb::velocypack;

namespace {
inline size_t ptrOverhead() { return sizeof(void*); }
}  // namespace

TEST(AqlValueSupervisedTest, CopyLargePayloadAndAccountPayloadAndPointer) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor monitor(global);
  ASSERT_EQ(monitor.current(), 0);

  Builder b;
  b.openArray();
  b.add(Value(std::string(2048, 'a')));  // force heap payload
  b.close();
  Slice s = b.slice();

  AqlValue v(monitor, s, false);

  const size_t payload = v.memoryUsage();
  const size_t expected = payload + ptrOverhead();
  EXPECT_EQ(monitor.current(), expected)
      << "must account for the payload + resource monitor ptr";
  v.destroy();
  EXPECT_EQ(monitor.current(), 0);
}

TEST(AqlValueSupervisedTest, InlineNoPayloadOnlyAccountPointer) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor monitor(global);

  Builder b;
  b.add(Value(42));  // fits inline
  Slice s = b.slice();

  AqlValue v(monitor, s, false);
  EXPECT_EQ(v.memoryUsage(), 0);
  EXPECT_EQ(monitor.current(), ptrOverhead());

  v.destroy();
  EXPECT_EQ(monitor.current(), 0);
}

TEST(AqlValueSupervisedTest, CloneSharedPayloadAccountOnlyPtr) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor monitor(global);

  Builder b;
  b.openArray();
  b.add(Value(std::string(4096, 'a')));  // heap payload
  b.close();
  Slice s = b.slice();

  AqlValue v(monitor, s, false);
  const size_t base = monitor.current();
  ASSERT_EQ(base, v.memoryUsage() + ptrOverhead());

  AqlValue c = v.clone();
  EXPECT_EQ(monitor.current(), base + ptrOverhead())
      << "clone must add only overhead of the resource monitor ptr";

  c.destroy();
  EXPECT_EQ(monitor.current(), base);

  v.destroy();
  EXPECT_EQ(monitor.current(), 0);
}

TEST(AqlValueSupervisedTest,
     DestroyOriginalAndCloneKeepAccountingUntilDestroyed) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor monitor(global);

  Builder b;
  b.openArray();
  b.add(Value(std::string(1024, 'z')));
  b.close();
  Slice s = b.slice();

  AqlValue v(monitor, s, false);
  AqlValue c = v.clone();

  v.destroy();
  EXPECT_GE(monitor.current(), ptrOverhead());

  c.destroy();
  EXPECT_EQ(monitor.current(), 0);
}

TEST(AqlValueSupervisedTest, AdoptmSupervisedBufferAccountOnlyPtr) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor monitor(global);

  SupervisedBuffer sb(monitor);
  Builder b(sb);
  b.openArray();
  b.add(Value(std::string(1500, 'a')));
  b.close();
  const size_t before = monitor.current();

  AqlValue v(monitor, b.slice(), true);

  EXPECT_EQ(monitor.current(), before + ptrOverhead());

  v.destroy();
  EXPECT_EQ(monitor.current(), before);
}
