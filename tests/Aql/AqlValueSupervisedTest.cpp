#include "gtest/gtest.h"

#include "Aql/AqlValue.h"
#include "Basics/GlobalResourceMonitor.h"
#include "Basics/ResourceUsage.h"
#include "Basics/SupervisedBuffer.h"

#include <velocypack/Builder.h>
#include <velocypack/Value.h>
#include <velocypack/Slice.h>
#include <velocypack/Buffer.h>

#include "Logger/LogMacros.h"

using namespace arangodb;
using namespace arangodb::aql;
using namespace arangodb::velocypack;

namespace {
using DocumentData = std::unique_ptr<std::string>;

inline size_t ptrOverhead() { return sizeof(ResourceMonitor*); }

inline Builder makeObj(
    std::initializer_list<std::pair<std::string, Value>> fields) {
  Builder b;
  b.openObject();
  for (auto const& [k, v] : fields) {
    b.add(k, v);
  }
  b.close();
  return b;
}

inline Builder makeArray(std::initializer_list<Value> vals) {
  Builder b;
  b.openArray();
  for (auto const& v : vals) {
    b.add(v);
  }
  b.close();
  return b;
}

inline Builder makeNumArray(size_t n) {
  Builder b;
  b.openArray();
  for (size_t i = 0; i < n; ++i) b.add(Value(static_cast<int>(i)));
  b.close();
  return b;
}

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

inline DocumentData makeDocDataFromSlice(Slice s) {
  auto const* p = reinterpret_cast<char const*>(s.start());
  return std::make_unique<std::string>(p, p + s.byteSize());
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
    EXPECT_EQ(static_cast<size_t>(l), 14);
  }
  EXPECT_EQ(aqlVal.slice().byteSize(), slice.byteSize());

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

TEST(AqlValueSupervisedTest, BoundaryOverInlineAccounts) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  auto builder = makeString(16, 'a');
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

  AqlValue aAdopt(slice2.begin());  // take a look

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

TEST(AqlValueSupervisedTest, AccountsAndMovesFromSource) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor rm(global);
  ASSERT_EQ(rm.current(), 0);

  auto s = makeString(4096, 'x').slice();
  auto data = makeDocDataFromSlice(s);

  auto tempPtr = data.get();
  AqlValue v(data, &rm);

  size_t expected = static_cast<size_t>(s.byteSize()) + ptrOverhead();
  EXPECT_EQ(v.memoryUsage(), expected);
  EXPECT_EQ(rm.current(), expected);


  // Source string should be empty
  EXPECT_EQ(data.get(), nullptr);
  EXPECT_EQ(tempPtr->size(), 0U);

  v.destroy();
  EXPECT_EQ(rm.current(), 0);
}

TEST(AqlValueSupervisedTest, MutipleValuesSumAccounting) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor rm(global);

  auto s1 = makeString(1500, 'a').slice();
  auto s2 = makeString(2500, 'b').slice();
  auto d1 = makeDocDataFromSlice(s1);
  auto d2 = makeDocDataFromSlice(s2);

  AqlValue v1(d1, &rm);
  AqlValue v2(d2, &rm);

  size_t e1 = static_cast<size_t>(s1.byteSize()) + ptrOverhead();
  size_t e2 = static_cast<size_t>(s2.byteSize()) + ptrOverhead();

  EXPECT_EQ(v1.memoryUsage(), e1);
  EXPECT_EQ(v2.memoryUsage(), e2);
  EXPECT_EQ(rm.current(), e1 + e2);

  v1.destroy();
  EXPECT_EQ(rm.current(), e2);

  v2.destroy();
  EXPECT_EQ(rm.current(), 0);
}

TEST(AqlValueSupervisedTest, CloneKeepsAccoutingUNtilBothDestroyed) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor rm(global);

  auto s = makeString(1500, 'z').slice();
  auto data = makeDocDataFromSlice(s);
  AqlValue v(data, &rm);

  size_t expected = static_cast<size_t>(s.byteSize()) + ptrOverhead();
  ASSERT_EQ(v.memoryUsage(), expected);
  ASSERT_EQ(rm.current(), expected);

  AqlValue cloned = v.clone();
  EXPECT_EQ(cloned.memoryUsage(), expected);
  EXPECT_EQ(rm.current(), expected + expected);

  v.destroy();
  EXPECT_EQ(rm.current(), expected);

  cloned.destroy();
  EXPECT_EQ(rm.current(), 0);
}

TEST(AqlValueSupervisedTest, ShortString_MemoryAccounting) {
  auto& global = GlobalResourceMonitor::instance();
  arangodb::ResourceMonitor rm(global);

  std::string s(15, 'x');  // 15 chars, fits short-string (<= 126), not inline
  const std::size_t payloadSize = 1 + s.size();  // tag + chars
  const std::uint64_t before = rm.current();

  AqlValue v(std::string_view{s}, &rm);

  // Memory should increase by kPrefix + payloadSize
  EXPECT_EQ(rm.current() - before, ptrOverhead() + payloadSize);

  // Slice should decode back to original string
  auto slice = v.slice();
  ASSERT_TRUE(slice.isString());
  EXPECT_EQ(slice.stringView(), s);

  v.destroy();
  // After destruction, usage returns to baseline
  EXPECT_EQ(rm.current(), before);
}

TEST(AqlValueSupervisedTest, LongString_ResourceMonitorUsage) {
  auto& global = GlobalResourceMonitor::instance();
  arangodb::ResourceMonitor rm(global);

  std::string s(300, 'A');  // triggers long string encoding
  std::size_t expectedBytes = ptrOverhead() + (1 + 8 + s.size());
  // prefix + 0xBF + 8-byte length + characters

  std::uint64_t before = rm.current();

  AqlValue v(std::string_view{s}, &rm);

  auto slice = v.slice();
  ASSERT_TRUE(slice.isString());
  EXPECT_EQ(slice.stringView(), s);

  std::uint64_t after = rm.current();
  EXPECT_EQ(after - before, expectedBytes);

  v.destroy();
  EXPECT_EQ(rm.current(), before);
}
TEST(AqlValueSupervisedTest, GetTypeString_Basics_SupervisedAndManaged) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor rm(global);

  // supervised string (short string path -> supervised slice in your impl)
  AqlValue ssv(std::string_view{"abcdef"}, &rm);
  EXPECT_EQ(std::string(ssv.getTypeString()), "string");
  ssv.destroy();

  // supervised array
  Builder arr = makeArray({Value(1), Value(2)});
  AqlValue asv(arr.slice(), 0, &rm);
  EXPECT_EQ(std::string(asv.getTypeString()), "array");
  asv.destroy();

  // inline number
  AqlValue n(AqlValueHintInt{42});
  EXPECT_EQ(std::string(n.getTypeString()), "number");

  // managed slice (no RM)
  Builder obj = makeObj({{"a", Value(1)}});
  AqlValue mv(obj.slice());
  EXPECT_EQ(std::string(mv.getTypeString()), "object");
  mv.destroy();
}

TEST(AqlValueSupervisedTest, Length_ArrayAndRange) {
  auto& g = GlobalResourceMonitor::instance();
  ResourceMonitor rm(g);

  Builder arr = makeNumArray(5);
  AqlValue a(arr.slice(), 0, &rm);
  EXPECT_EQ(a.length(), 5U);
  a.destroy();

  AqlValue r(3, 7);  // inclusive range [3..7] => length 5
  EXPECT_EQ(r.length(), 5U);
  r.destroy();
}

TEST(AqlValueSupervisedTest, At_DoCopy_And_NoCopy_Supervised) {
  auto& g = GlobalResourceMonitor::instance();
  ResourceMonitor rm(g);

  Builder arr = makeArray({Value(11), Value(22), Value(33)});
  AqlValue a(arr.slice(), 0, &rm);

  bool mustDestroy = false;
  // doCopy = false → return slice reference (mustDestroy=false)
  AqlValue e0 = a.at(1, mustDestroy, /*doCopy*/ false);
  EXPECT_FALSE(mustDestroy);
  EXPECT_EQ(e0.toInt64(), 22);
  // no destroy required
  // doCopy = true → makes owning value (mustDestroy=true)
  AqlValue e1 = a.at(2, mustDestroy, /*doCopy*/ true);
  EXPECT_TRUE(mustDestroy);
  EXPECT_EQ(e1.toInt64(), 33);
  e1.destroy();

  a.destroy();
}

TEST(AqlValueSupervisedTest, At_WithSizeOverload_NegativeIndexing) {
  auto& g = GlobalResourceMonitor::instance();
  ResourceMonitor rm(g);

  Builder arr = makeArray({Value(1), Value(2), Value(3)});
  Slice s = arr.slice();
  AqlValue a(s, 0, &rm);

  bool mustDestroy = false;
  // request with explicit size, negative index
  AqlValue e = a.at(-1, s.length(), mustDestroy, /*copy*/ false);
  EXPECT_EQ(e.toInt64(), 3);
  a.destroy();
}

TEST(AqlValueSupervisedTest, ToDouble_Various) {
  // inline integer
  AqlValue i(AqlValueHintInt{42});
  bool failed = false;
  EXPECT_DOUBLE_EQ(i.toDouble(failed), 42.0);
  EXPECT_FALSE(failed);

  // from boolean
  AqlValue b(AqlValueHintBool{true});
  EXPECT_DOUBLE_EQ(b.toDouble(), 1.0);

  // from string number
  Builder sb;
  sb.add(Value("123"));
  AqlValue sv(sb.slice());
  EXPECT_DOUBLE_EQ(sv.toDouble(), 123.0);
  sv.destroy();

  // singleton array unwrap
  Builder arr = makeArray({Value(7)});
  AqlValue av(arr.slice());
  EXPECT_DOUBLE_EQ(av.toDouble(), 7.0);
  av.destroy();
}

TEST(AqlValueSupervisedTest, ToInt64_Various) {
  AqlValue d(AqlValueHintDouble{5.0});
  EXPECT_EQ(d.toInt64(), 5);

  Builder s;
  s.add(Value("99"));
  AqlValue sv(s.slice());
  EXPECT_EQ(sv.toInt64(), 99);
  sv.destroy();

  // singleton array forward
  Builder arr = makeArray({Value(8)});
  AqlValue a(arr.slice());
  EXPECT_EQ(a.toInt64(), 8);
  a.destroy();
}

TEST(AqlValueSupervisedTest, ToBoolean_Various) {
  AqlValue zero(AqlValueHintInt{0});
  EXPECT_FALSE(zero.toBoolean());
  AqlValue one(AqlValueHintInt{1});
  EXPECT_TRUE(one.toBoolean());

  Builder s;
  s.add(Value(""));  // empty string
  AqlValue sv(s.slice());
  EXPECT_FALSE(sv.toBoolean());
  sv.destroy();

  Builder obj = makeObj({{"a", Value(1)}});
  AqlValue ov(obj.slice());
  EXPECT_TRUE(ov.toBoolean());  // objects are truthy
  ov.destroy();

  Builder arr = makeArray({Value(1), Value(2)});
  AqlValue av(arr.slice());
  EXPECT_TRUE(av.toBoolean());
  av.destroy();
}

TEST(AqlValueSupervisedTest,
     DataPointer_MatchesSliceBegin_ForSupervisedAndManaged) {
  auto& g = GlobalResourceMonitor::instance();
  ResourceMonitor rm(g);

  // supervised (with RM)
  std::string big1(300, 'a');
  Builder b1;
  b1.add(Value(big1));
  Slice s1 = b1.slice();
  AqlValue sv(s1, 0, &rm);
  EXPECT_EQ(static_cast<uint8_t const*>(sv.data()), sv.slice().start());
  sv.destroy();

  // managed (no RM, large enough to be out-of-line)
  std::string big2(300, 'a');
  Builder b2;
  b2.add(Value(big2));
  AqlValue mv(b2.slice());
  EXPECT_EQ(static_cast<uint8_t const*>(mv.data()), mv.slice().start());
  mv.destroy();
}

TEST(AqlValueSupervisedTest, ToVelocyPack_Roundtrip_Supervised) {
  auto& g = GlobalResourceMonitor::instance();
  ResourceMonitor rm(g);

  Builder src = makeObj({{"a", Value(1)}, {"b", Value("x")}});
  AqlValue v(src.slice(), 0, &rm);

  Builder out;
  v.toVelocyPack(nullptr, out, /*allowUnindexed*/ true);
  EXPECT_TRUE(out.slice().binaryEquals(src.slice()));

  v.destroy();
}

// This test checks the behavior of materialize() function's default case
TEST(AqlValueSupervisedTest, Materialize_NonRange) {
  /* Non-range SupervisedSlice */
  auto& g = GlobalResourceMonitor::instance();
  ResourceMonitor rm(g);

  std::string big(8 * 1024, 'x');
  Builder obj;
  obj.openObject();
  obj.add("q", Value(7));
  obj.add("big", Value(big));
  obj.close();

  AqlValue v1(obj.slice(), /*length*/ 0, &rm);  // SupervisedSlice
  std::uint64_t base = rm.current();

  bool copied1 = true;
  AqlValue mat1 = v1.materialize(nullptr, copied1);
  // materialize()'s default case calls copy ctor of SupervisedSlice
  // Copy ctor of SupervisedSlice creates a new copy of AqlValue
  EXPECT_FALSE(copied1); // This should be true

  EXPECT_TRUE(v1.slice().binaryEquals(obj.slice()));
  EXPECT_TRUE(mat1.slice().binaryEquals(obj.slice()));

  // Because there are two copies of SupervisedSlice AqlValues
  EXPECT_EQ(rm.current(), 2 * base);

  mat1.destroy();
  EXPECT_EQ(rm.current(), base);

  v1.destroy();
  EXPECT_EQ(rm.current(), 0);

  /* Non-range SupervisedString */
  std::string bigStr(16 * 1024, 'y');  // 16KB string
  AqlValue v2(std::string_view{bigStr}, &rm);  // SupervisedString
  base = rm.current();

  bool copied2 = false;
  AqlValue mat2 = v2.materialize(nullptr, copied2);
  EXPECT_FALSE(copied2);
  EXPECT_TRUE(mat2.slice().isString());
  EXPECT_EQ(mat2.slice().stringView(), bigStr);

  EXPECT_EQ(rm.current(), 2 * base);  // cloned supervised string accounted

  mat2.destroy();
  EXPECT_EQ(rm.current(), base);

  v2.destroy();
  EXPECT_EQ(rm.current(), 0);
}

TEST(AqlValueSupervisedTest, Slice_TypedDispatch) {
  // ensure slice() and slice(type) consistent
  Builder b;
  b.add(Value("hello"));
  AqlValue v(b.slice());
  auto st = v.type();
  EXPECT_TRUE(v.slice().binaryEquals(v.slice(st)));
  v.destroy();
}

TEST(AqlValueSupervisedTest, Equality_SupervisedVsManaged_ContentEqual) {
  auto& g = GlobalResourceMonitor::instance();
  ResourceMonitor rm(g);

  Builder doc = makeObj({{"a", Value(1)}, {"b", Value("qq")}});
  Slice s = doc.slice();

  AqlValue sup(s, 0, &rm);  // supervised
  AqlValue man(s);          // managed (no RM)

  std::equal_to<AqlValue> eq;
  EXPECT_TRUE(eq(sup, man));

  sup.destroy();
  man.destroy();
}

TEST(AqlValueSupervisedTest, HasKey_ObjectVsNonObject) {
  auto& g = GlobalResourceMonitor::instance();
  ResourceMonitor rm(g);

  // supervised object
  Builder obj = makeObj({{"a", Value(1)}, {"b", Value("x")}});
  AqlValue v(obj.slice(), 0, &rm);
  EXPECT_TRUE(v.hasKey("a"));
  EXPECT_TRUE(v.hasKey("b"));
  EXPECT_FALSE(v.hasKey("c"));
  v.destroy();

  // non-object (array)
  Builder arr = makeArray({Value(1), Value(2)});
  AqlValue a(arr.slice(), 0, &rm);
  EXPECT_FALSE(a.hasKey("a"));
  a.destroy();
}

TEST(AqlValueSupervisedTest, Compare_NumericCrossForms) {
  // int64 vs uint64/double
  AqlValue i(AqlValueHintInt{42});
  AqlValue u(AqlValueHintUInt{42});
  AqlValue d(AqlValueHintDouble{42.0});
  AqlValue i2(AqlValueHintInt{43});

  EXPECT_EQ(AqlValue::Compare(nullptr, i, u, /*utf8*/ false), 0);
  EXPECT_EQ(AqlValue::Compare(nullptr, i, d, /*utf8*/ false), 0);
  EXPECT_LT(AqlValue::Compare(nullptr, i, i2, /*utf8*/ false), 0);
  EXPECT_GT(AqlValue::Compare(nullptr, i2, d, /*utf8*/ false), 0);
}

TEST(AqlValueSupervisedTest, Compare_SupervisedVsManaged_EqualContent) {
  auto& g = GlobalResourceMonitor::instance();
  ResourceMonitor rm(g);

  Builder b = makeObj({{"k", Value(1)}, {"s", Value("v")}});
  Slice s = b.slice();

  AqlValue sup(s, 0, &rm);  // supervised
  AqlValue man(s);          // managed

  EXPECT_EQ(AqlValue::Compare(nullptr, sup, man, /*utf8*/ true), 0);
  sup.destroy();
  man.destroy();
}

TEST(AqlValueSupervisedTest, Compare_RangeOrdering) {
  // [1..3] vs [1..4] → smaller high is less
  AqlValue r1(1, 3);
  AqlValue r2(1, 4);
  EXPECT_LT(AqlValue::Compare(nullptr, r1, r2, /*utf8*/ false), 0);

  // [2..4] vs [1..4] → larger low is greater
  AqlValue r3(2, 4);
  EXPECT_GT(AqlValue::Compare(nullptr, r3, r2, /*utf8*/ false), 0);

  // equal
  AqlValue r4(2, 4);
  EXPECT_EQ(AqlValue::Compare(nullptr, r3, r4, /*utf8*/ false), 0);

  r1.destroy();
  r2.destroy();
  r3.destroy();
  r4.destroy();
}