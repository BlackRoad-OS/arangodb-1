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

inline Slice makeLargeArray(size_t n = 2048, char bytesToFill = 'a') {
  Builder builder;
  builder.openArray();
  builder.add(Value(std::string(n, bytesToFill)));
  builder.close();
  return builder.slice();
}
inline Slice makeString(size_t n, char bytesToFill = 'a') {
  Builder builder;
  builder.add(Value(std::string(n, bytesToFill)));
  return builder.slice();
}
inline Slice makeArrayOfNumbers(size_t n = 5) {
  Builder builder;
  builder.openArray();
  for (size_t i = 0; i < n; ++i) builder.add(Value(static_cast<int>(i)));
  builder.close();
  return builder.slice();
}

inline size_t findNonInlineThreshold(ResourceMonitor& resourceMonitor) {
  for (size_t len = 1; len < 4096; ++len) {
    Slice slice = makeString(len, 'a');
    AqlValue aqlVal(resourceMonitor, slice);
    size_t memUsage = aqlVal.memoryUsage();
    aqlVal.destroy();
    if (memUsage > 0) return len;
  }
  return 1024;
}
}  // namespace

TEST(AqlValueSupervisedTest, SliceOwnedAccountsPayloadPrefix) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);
  ASSERT_EQ(resourceMonitor.current(), 0u);

  Slice slice = makeLargeArray(4096, 'a');
  AqlValue aqlVal(resourceMonitor, slice);

  EXPECT_EQ(resourceMonitor.current(), aqlVal.memoryUsage());
  EXPECT_EQ(aqlVal.memoryUsage(),
            static_cast<size_t>(slice.byteSize()) + ptrOverhead());

  EXPECT_TRUE(aqlVal.slice().isArray());
  EXPECT_EQ(aqlVal.slice().at(0).getStringUnchecked().size(), 4096u);

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0u);
}

TEST(AqlValueSupervisedTest, SliceLengthOwnedMatchesSliceCtor) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  Slice slice = makeLargeArray(1024, 'a');
  AqlValue aqlVal(resourceMonitor, slice,
                  static_cast<ValueLength>(slice.byteSize()));

  EXPECT_EQ(resourceMonitor.current(), aqlVal.memoryUsage());
  EXPECT_EQ(aqlVal.memoryUsage(),
            static_cast<size_t>(slice.byteSize()) + ptrOverhead());

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0u);
}

TEST(AqlValueSupervisedTest, BytesLengthOwnedAccountsPayloadPrefix) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  Slice slice = makeLargeArray(1536, 'a');
  AqlValue aqlVal(resourceMonitor, slice.begin(),
                  static_cast<ValueLength>(slice.byteSize()));

  EXPECT_EQ(resourceMonitor.current(), aqlVal.memoryUsage());
  EXPECT_EQ(aqlVal.memoryUsage(),
            static_cast<size_t>(slice.byteSize()) + ptrOverhead());

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0u);
}

TEST(AqlValueSupervisedTest, BufferOwnedAccountsPayloadPrefix) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  Slice slice = makeLargeArray(2048, 'a');
  velocypack::Buffer<uint8_t> buffer;
  buffer.append(slice.start(), slice.byteSize());

  AqlValue aqlVal(resourceMonitor, buffer);
  EXPECT_EQ(resourceMonitor.current(), aqlVal.memoryUsage());
  EXPECT_EQ(aqlVal.memoryUsage(),
            static_cast<size_t>(slice.byteSize()) + ptrOverhead());

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0u);
}

TEST(AqlValueSupervisedTest, HintSliceCopyOwnedAccountsPayloadPrefix) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  Slice slice = makeLargeArray(512, 'a');
  AqlValue::AqlValueHintSliceCopy hint{slice};
  AqlValue aqlVal(resourceMonitor, hint);

  EXPECT_EQ(resourceMonitor.current(), aqlVal.memoryUsage());
  EXPECT_EQ(aqlVal.memoryUsage(),
            static_cast<size_t>(slice.byteSize()) + ptrOverhead());

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0u);
}

TEST(AqlValueSupervisedTest, InlineNotAccount) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  size_t threshold = findNonInlineThreshold(resourceMonitor);
  ASSERT_GT(threshold, 1u);
  size_t inlineLen = threshold - 1;

  Slice slice = makeString(inlineLen, 'a');
  AqlValue aqlVal(resourceMonitor, slice);

  EXPECT_EQ(aqlVal.memoryUsage(), 0);
  EXPECT_EQ(resourceMonitor.current(), 0);
  EXPECT_TRUE(aqlVal.slice().isString());
  EXPECT_EQ(aqlVal.slice().getStringUnchecked().size(), inlineLen);
  EXPECT_EQ(aqlVal.slice().byteSize(), slice.byteSize());

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

TEST(AqlValueSupervisedTest, BoundaryOverInlineAccounts) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  size_t threshold = findNonInlineThreshold(resourceMonitor);
  Slice slice = makeString(threshold, 'a');  // should be non-inline now
  AqlValue aqlVal(resourceMonitor, slice);

  EXPECT_GT(aqlVal.memoryUsage(), 0);
  EXPECT_EQ(aqlVal.memoryUsage(),
            static_cast<size_t>(slice.byteSize()) + ptrOverhead());
  EXPECT_EQ(resourceMonitor.current(), aqlVal.memoryUsage());

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

TEST(AqlValueSupervisedTest, AdoptedSetPointerNoAccount) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  Slice sliceA = makeLargeArray(3072, 'a');
  Slice sliceB = makeLargeArray(3072, 'b');

  AqlValue aqlVal(resourceMonitor, sliceA);  // owned copy
  size_t billed = resourceMonitor.current();
  ASSERT_EQ(billed, aqlVal.memoryUsage());
  ASSERT_GE(billed, ptrOverhead());

  // setPointer(): supervised kinds flip to Adopted & recompute header length
  aqlVal.setPointer(const_cast<uint8_t*>(sliceB.start()));
  EXPECT_EQ(resourceMonitor.current(), billed);
  EXPECT_EQ(aqlVal.memoryUsage(), 0);

  aqlVal.destroy();  // adopted destroy: must not unbill or free payload
  EXPECT_EQ(resourceMonitor.current(), billed);

  AqlValue aqlVal2(resourceMonitor, sliceB);  // new owned instance
  EXPECT_EQ(resourceMonitor.current(), billed + aqlVal2.memoryUsage());

  aqlVal2.destroy();
  EXPECT_EQ(resourceMonitor.current(), billed);
}

TEST(AqlValueSupervisedTest, OwnedSetPointerKeepsAccountingDestroy) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  Slice sliceOwned = makeLargeArray(1800, 'a');
  Slice sliceAdopt = makeLargeArray(1600, 'b');

  AqlValue aqlVal(resourceMonitor, sliceOwned);
  size_t billed = resourceMonitor.current();
  ASSERT_GT(billed, 0);

  aqlVal.setPointer(const_cast<uint8_t*>(sliceAdopt.start()));
  EXPECT_EQ(resourceMonitor.current(), billed);
  EXPECT_EQ(aqlVal.memoryUsage(), 0);

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), billed);
}

TEST(AqlValueSupervisedTest, OwnedThenAdoptedDoesNotChangeAccounting) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  Slice sliceA = makeLargeArray(1500, 'a');
  Slice sliceB = makeLargeArray(1500, 'b');

  AqlValue aqlVal1(resourceMonitor, sliceA);
  size_t base = resourceMonitor.current();
  ASSERT_EQ(base, aqlVal1.memoryUsage());
  ASSERT_GE(base, ptrOverhead());

  AqlValue aqlVal2(resourceMonitor, sliceB);
  aqlVal2.setPointer(
      const_cast<uint8_t*>(aqlVal1.slice().begin()));  // adopt view
  EXPECT_EQ(resourceMonitor.current(), base);
  EXPECT_EQ(aqlVal2.memoryUsage(), 0);

  aqlVal2.destroy();
  EXPECT_EQ(resourceMonitor.current(), base);

  aqlVal1.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

TEST(AqlValueSupervisedTest, AdoptSupervisedBufferDoesNotAccountOrFree) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  SupervisedBuffer supervised(
      resourceMonitor);  // builder that already accounts payload
  Builder builder(supervised);
  builder.openArray();
  builder.add(Value(std::string(1500, 'a')));
  builder.close();

  const size_t before = resourceMonitor.current();
  ASSERT_GT(before, 0);

  // Start with inline, then adopt external bytes from the supervised buffer
  Builder tiny;
  tiny.add(Value(7));
  AqlValue aqlVal(resourceMonitor, tiny.slice());  // inline -> 0 accounting
  ASSERT_EQ(aqlVal.memoryUsage(), 0);
  ASSERT_EQ(resourceMonitor.current(), before);

  aqlVal.setPointer(
      const_cast<uint8_t*>(builder.slice().start()));  // adopt external
  EXPECT_EQ(aqlVal.memoryUsage(), 0);
  EXPECT_EQ(resourceMonitor.current(), before);

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), before);
}

TEST(AqlValueSupervisedTest, CloneSharedPayloadAccountOnlyPtr) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  Builder builder;
  builder.openArray();
  builder.add(Value(std::string(4096, 'a')));
  builder.close();
  Slice slice = builder.slice();

  AqlValue aqlVal1(resourceMonitor, slice);
  const size_t base = resourceMonitor.current();
  ASSERT_EQ(base, aqlVal1.memoryUsage());

  AqlValue aqlVal2 = aqlVal1.clone();
  // clone adds only handle overhead (pointer-sized)
  EXPECT_EQ(resourceMonitor.current(), base + ptrOverhead());

  aqlVal2.destroy();
  EXPECT_EQ(resourceMonitor.current(), base);

  aqlVal1.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
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

  AqlValue aqlVal(resourceMonitor, slice);
  AqlValue cloneVal = aqlVal.clone();

  aqlVal.destroy();
  EXPECT_GE(resourceMonitor.current(), ptrOverhead());

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

  AqlValue aqlVal(resourceMonitor, slice);
  size_t base = resourceMonitor.current();

  AqlValue c = aqlVal.clone();
  EXPECT_EQ(resourceMonitor.current(), base + ptrOverhead());

  c.erase();  // should not drop accounting
  EXPECT_EQ(resourceMonitor.current(), base + ptrOverhead());

  c.destroy();
  EXPECT_EQ(resourceMonitor.current(), base);

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

TEST(AqlValueSupervisedTest, TypeArrayNumberStringNullObjectNone) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  {
    Slice slice = makeArrayOfNumbers(16);
    AqlValue aqlVal(resourceMonitor, slice);
    EXPECT_TRUE(aqlVal.isArray());
    EXPECT_FALSE(aqlVal.isObject());
    EXPECT_FALSE(aqlVal.isString());
    EXPECT_FALSE(aqlVal.isNull());
    aqlVal.destroy();
  }
  {
    Slice slice = makeString(4096, 'a');
    AqlValue aqlVal(resourceMonitor, slice);
    EXPECT_TRUE(aqlVal.isString());
    EXPECT_FALSE(aqlVal.isArray());
    EXPECT_FALSE(aqlVal.isNumber());
    aqlVal.destroy();
  }
  {
    Builder builder;
    builder.add(Value(ValueType::Null));
    Slice slice = builder.slice();
    AqlValue aqlVal(resourceMonitor, slice);
    EXPECT_TRUE(aqlVal.isNull());
    EXPECT_FALSE(aqlVal.isNumber());
    aqlVal.destroy();
  }

  EXPECT_EQ(resourceMonitor.current(), 0);
}

TEST(AqlValueSupervisedTest, PayloadLengthsMatchPrefixNotCounted) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  Slice slice = makeLargeArray(1234, 'a');
  AqlValue aqlVal(resourceMonitor, slice);

  EXPECT_EQ(aqlVal.slice().byteSize(), slice.byteSize());
  EXPECT_EQ(aqlVal.memoryUsage(),
            static_cast<size_t>(aqlVal.slice().byteSize()) + ptrOverhead());

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

TEST(AqlValueSupervisedTest, MultipleOwnedSumAccounting) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  Slice sliceA = makeLargeArray(1000, 'a');
  Slice sliceB = makeLargeArray(2000, 'b');
  Slice sliceC = makeLargeArray(3000, 'c');

  AqlValue aqlVal1(resourceMonitor, sliceA);
  AqlValue aqlVal2(resourceMonitor, sliceB);
  AqlValue aqlVal3(resourceMonitor, sliceC);

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

TEST(AqlValueSupervisedTest, FuzzAroundInlineThreshold) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  size_t t = findNonInlineThreshold(resourceMonitor);
  for (int delta = -3; delta <= 3; ++delta) {
    size_t n =
        static_cast<size_t>(std::max<long>(1, static_cast<long>(t) + delta));
    Slice slice = makeString(n, 'a');
    AqlValue aqlVal(resourceMonitor, slice);
    size_t mu = aqlVal.memoryUsage();

    if (n < t) {
      EXPECT_EQ(mu, 0) << "n=" << n << " should be inline";
      EXPECT_EQ(resourceMonitor.current(), 0);
    } else {
      size_t expected = static_cast<size_t>(slice.byteSize()) + ptrOverhead();
      EXPECT_EQ(mu, expected) << "n=" << n << " should be owned";
      EXPECT_EQ(resourceMonitor.current(), expected);
    }
    aqlVal.destroy();
    EXPECT_EQ(resourceMonitor.current(), 0);
  }
}

TEST(AqlValueSupervisedTest, DestroySafe) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  Slice slice = makeLargeArray(2000, 'a');
  AqlValue aqlVal(resourceMonitor, slice);
  size_t billed = resourceMonitor.current();
  EXPECT_GT(billed, 0);

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}
