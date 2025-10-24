#include "gtest/gtest.h"

#include "Aql/AqlValue.h"
#include "Basics/GlobalResourceMonitor.h"
#include "Basics/ResourceUsage.h"
#include "Basics/SupervisedBuffer.h"

#include <velocypack/Builder.h>
#include <velocypack/Value.h>
#include <velocypack/Slice.h>
#include <velocypack/Buffer.h>

using namespace arangodb;
using namespace arangodb::aql;
using namespace arangodb::velocypack;

namespace {
inline size_t ptrOverhead() { return sizeof(ResourceMonitor*); }

inline Builder makeLargeArray(size_t n = 2048, char bytesToFill = 'a') {
  Builder b;
  b.openArray();
  b.add(Value(std::string(n, bytesToFill)));
  b.close();
  return b;
}
inline Builder makeString(size_t n, char bytesToFill = 'a') {
  Builder b;
  b.add(Value(std::string(n, bytesToFill)));
  return b;
}
inline Builder makeArrayOfNumbers(size_t n = 5) {
  Builder b;
  b.openArray();
  for (size_t i = 0; i < n; ++i) b.add(Value(static_cast<int>(i)));
  b.close();
  return b;
}
}  // namespace

TEST(AqlValueSupervisedTest, SliceOwnedAccountsPayloadPrefix) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);
  ASSERT_EQ(resourceMonitor.current(), 0);

  auto builder = makeLargeArray(4096, 'a');
  Slice slice = builder.slice();
  AqlValue aqlVal(slice, 0, &resourceMonitor);

  EXPECT_EQ(resourceMonitor.current(), aqlVal.memoryUsage());
  EXPECT_EQ(aqlVal.memoryUsage(),
            static_cast<size_t>(slice.byteSize()) + ptrOverhead());

  EXPECT_TRUE(aqlVal.slice().isArray());
  {
    ValueLength l = 0;
    (void)aqlVal.slice().at(0).getStringUnchecked(l);
    EXPECT_EQ(l, 4096);
  }

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

TEST(AqlValueSupervisedTest, SliceLengthOwnedMatchesSliceCtor) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  auto builder = makeLargeArray(1024, 'a');
  Slice slice = builder.slice();
  AqlValue aqlVal(slice, static_cast<ValueLength>(slice.byteSize()),
                  &resourceMonitor);

  EXPECT_EQ(resourceMonitor.current(), aqlVal.memoryUsage());
  EXPECT_EQ(aqlVal.memoryUsage(),
            static_cast<size_t>(slice.byteSize()) + ptrOverhead());

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

TEST(AqlValueSupervisedTest, BufferOwnedAccountsPayloadPrefix) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  auto builder = makeLargeArray(2048, 'a');
  Slice slice = builder.slice();
  velocypack::Buffer<uint8_t> buffer;
  buffer.append(slice.start(), slice.byteSize());

  AqlValue aqlVal(buffer, &resourceMonitor);
  EXPECT_EQ(resourceMonitor.current(), aqlVal.memoryUsage());
  EXPECT_EQ(aqlVal.memoryUsage(),
            static_cast<size_t>(slice.byteSize()) + ptrOverhead());

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

TEST(AqlValueSupervisedTest, HintSliceCopyOwnedAccountsPayloadPrefix) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  auto builder = makeLargeArray(512, 'a');
  Slice slice = builder.slice();
  AqlValueHintSliceCopy hint{slice};
  AqlValue aqlVal(hint, &resourceMonitor);

  EXPECT_EQ(resourceMonitor.current(), aqlVal.memoryUsage());
  EXPECT_EQ(aqlVal.memoryUsage(),
            static_cast<size_t>(slice.byteSize()) + ptrOverhead());

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

TEST(AqlValueSupervisedTest, InlineNotAccount) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  auto builder = makeString(14, 'a');
  Slice slice = builder.slice();
  AqlValue aqlVal(slice, 0, &resourceMonitor);

  EXPECT_EQ(aqlVal.memoryUsage(), 0);
  EXPECT_EQ(resourceMonitor.current(), 0);
  EXPECT_TRUE(aqlVal.slice().isString());
  {
    ValueLength l = 0;
    (void)aqlVal.slice().getStringUnchecked(l);
    EXPECT_EQ(static_cast<size_t>(l), 15);
  }
  EXPECT_EQ(aqlVal.slice().byteSize(), slice.byteSize());

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

TEST(AqlValueSupervisedTest, BoundaryOverInlineAccounts) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  auto builder = makeString(15, 'a');
  Slice slice = builder.slice();
  AqlValue aqlVal(slice, 0, &resourceMonitor);

  EXPECT_GT(aqlVal.memoryUsage(), 0);
  EXPECT_EQ(aqlVal.memoryUsage(),
            static_cast<size_t>(slice.byteSize()) + ptrOverhead());
  EXPECT_EQ(resourceMonitor.current(), aqlVal.memoryUsage());

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

TEST(AqlValueSupervisedTest, AdoptedBytesCtorNoAccount) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  auto builder1 = makeLargeArray(3072, 'a');
  auto builder2 = makeLargeArray(3072, 'b');
  Slice slice1 = builder1.slice();
  Slice slice2 = builder2.slice();

  AqlValue aOwned(slice1, 0, &resourceMonitor);
  size_t billed = resourceMonitor.current();
  ASSERT_EQ(billed, aOwned.memoryUsage());
  ASSERT_GE(billed, ptrOverhead());

  AqlValue aAdopt(slice2.begin());

  EXPECT_EQ(resourceMonitor.current(), billed);
  EXPECT_EQ(aAdopt.memoryUsage(), 0);

  aAdopt.destroy();
  EXPECT_EQ(resourceMonitor.current(), billed);

  aOwned.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

TEST(AqlValueSupervisedTest, OwnedThenAdoptedElsewhereDoesNotChangeAccounting) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  auto builder1 = makeLargeArray(1500, 'a');
  auto builder2 = makeLargeArray(1500, 'b');
  Slice slice1 = builder1.slice();
  Slice slice2 = builder2.slice();

  AqlValue aOwned(slice1, 0, &resourceMonitor);
  size_t base = resourceMonitor.current();
  ASSERT_EQ(base, aOwned.memoryUsage());
  ASSERT_GE(base, ptrOverhead());

  AqlValue aAdoptB(slice2.begin());
  EXPECT_EQ(resourceMonitor.current(), base);
  EXPECT_EQ(aAdoptB.memoryUsage(), 0);

  aAdoptB.destroy();
  EXPECT_EQ(resourceMonitor.current(), base);

  aOwned.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

TEST(AqlValueSupervisedTest, AdoptSupervisedBufferDoesNotAccountOrFree) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  SupervisedBuffer supervised(resourceMonitor);
  Builder builder(supervised);
  builder.openArray();
  builder.add(Value(std::string(1500, 'a')));
  builder.close();

  const size_t before = resourceMonitor.current();
  ASSERT_GT(before, 0);

  Builder builder2;
  builder2.add(Value(7));
  AqlValue inlineVal(builder2.slice(), 0, &resourceMonitor);
  ASSERT_EQ(inlineVal.memoryUsage(), 0);
  ASSERT_EQ(resourceMonitor.current(), before);

  AqlValue adopted(builder2.slice().begin());
  EXPECT_EQ(adopted.memoryUsage(), 0);
  EXPECT_EQ(resourceMonitor.current(), before);

  adopted.destroy();
  inlineVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), before);
}

TEST(AqlValueSupervisedTest,
     DestroyOriginalAndCloneKeepAccountingUntilDestroyed) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  Builder builder;
  builder.openArray();
  builder.add(Value(std::string(1024, 'a')));
  builder.close();
  Slice slice = builder.slice();

  AqlValue aqlVal(slice, 0, &resourceMonitor);
  AqlValue cloneVal = aqlVal.clone();
  EXPECT_EQ(resourceMonitor.current(),
            aqlVal.memoryUsage() + cloneVal.memoryUsage());

  aqlVal.destroy();

  EXPECT_EQ(resourceMonitor.current(), cloneVal.memoryUsage());

  cloneVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

TEST(AqlValueSupervisedTest, CloneEraseKeepAccounting) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  Builder builder;
  builder.openArray();
  builder.add(Value(std::string(1024, 'a')));
  builder.close();
  Slice slice = builder.slice();

  AqlValue aqlVal(slice, 0, &resourceMonitor);
  size_t base = resourceMonitor.current();

  AqlValue c = aqlVal.clone();
  EXPECT_EQ(resourceMonitor.current(), base + c.memoryUsage());

  c.erase();
  EXPECT_EQ(resourceMonitor.current(), base);

  c.destroy();
  EXPECT_EQ(resourceMonitor.current(), base);

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

TEST(AqlValueSupervisedTest, TypeArrayNumberStringNullObjectNone) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  {
    auto b = makeArrayOfNumbers(16);
    Slice slice = b.slice();
    AqlValue aqlVal(slice, 0, &resourceMonitor);
    EXPECT_TRUE(aqlVal.isArray());
    EXPECT_FALSE(aqlVal.isObject());
    EXPECT_FALSE(aqlVal.isString());
    EXPECT_FALSE(aqlVal.isNull(false));
    aqlVal.destroy();
  }
  {
    auto b = makeString(4096, 'a');
    Slice slice = b.slice();
    AqlValue aqlVal(slice, 0, &resourceMonitor);
    EXPECT_TRUE(aqlVal.isString());
    EXPECT_FALSE(aqlVal.isArray());
    EXPECT_FALSE(aqlVal.isNumber());
    aqlVal.destroy();
  }
  {
    Builder builder;
    builder.add(Value(ValueType::Null));
    Slice slice = builder.slice();
    AqlValue aqlVal(slice, 0, &resourceMonitor);
    EXPECT_TRUE(aqlVal.isNull(false));
    EXPECT_FALSE(aqlVal.isNumber());
    aqlVal.destroy();
  }

  EXPECT_EQ(resourceMonitor.current(), 0);
}

TEST(AqlValueSupervisedTest, PayloadLengthsMatchPrefixNotCounted) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  auto b = makeLargeArray(1234, 'a');
  Slice slice = b.slice();
  AqlValue aqlVal(slice, 0, &resourceMonitor);

  EXPECT_EQ(aqlVal.slice().byteSize(), slice.byteSize());
  EXPECT_EQ(aqlVal.memoryUsage(),
            static_cast<size_t>(aqlVal.slice().byteSize()) + ptrOverhead());

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

TEST(AqlValueSupervisedTest, MultipleOwnedSumAccounting) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  auto bA = makeLargeArray(1000, 'a');
  auto bB = makeLargeArray(2000, 'b');
  auto bC = makeLargeArray(3000, 'c');
  Slice sliceA = bA.slice();
  Slice sliceB = bB.slice();
  Slice sliceC = bC.slice();

  AqlValue aqlVal1(sliceA, 0, &resourceMonitor);
  AqlValue aqlVal2(sliceB, 0, &resourceMonitor);
  AqlValue aqlVal3(sliceC, 0, &resourceMonitor);

  size_t exp1 = static_cast<size_t>(sliceA.byteSize()) + ptrOverhead();
  size_t exp2 = static_cast<size_t>(sliceB.byteSize()) + ptrOverhead();
  size_t exp3 = static_cast<size_t>(sliceC.byteSize()) + ptrOverhead();

  EXPECT_EQ(
      resourceMonitor.current(),
      aqlVal1.memoryUsage() + aqlVal2.memoryUsage() + aqlVal3.memoryUsage());
  EXPECT_EQ(resourceMonitor.current(), exp1 + exp2 + exp3);

  aqlVal2.destroy();
  EXPECT_EQ(resourceMonitor.current(), exp1 + exp3);

  aqlVal1.destroy();
  EXPECT_EQ(resourceMonitor.current(), exp3);

  aqlVal3.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

TEST(AqlValueSupervisedTest, DestroySafe) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  auto b = makeLargeArray(2000, 'a');
  Slice slice = b.slice();
  AqlValue aqlVal(slice, 0, &resourceMonitor);
  size_t billed = resourceMonitor.current();
  EXPECT_GT(billed, 0);

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}
