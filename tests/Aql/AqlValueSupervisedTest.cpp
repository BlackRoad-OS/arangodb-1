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

// Test for AqlValue(DocumentData&, ResourceMonitor* = nullptr)
TEST(AqlValueSupervisedTest, DocumentDataCtorAccountsCorrectSize) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor rm(global);
  ASSERT_EQ(rm.current(), 0);

  auto s = makeString(4096, 'x').slice();
  auto data = makeDocDataFromSlice(s);

  AqlValue v(data, &rm);
  EXPECT_EQ(data.get(), nullptr);  // Source string should be empty

  size_t expected = static_cast<size_t>(s.byteSize()) + ptrOverhead();
  // checks correct counting with internal logic
  EXPECT_EQ(v.memoryUsage(), expected);
  // checks correct counting with external logic
  EXPECT_EQ(rm.current(), expected);
  EXPECT_TRUE(v.slice().binaryEquals(s));

  v.destroy();
  EXPECT_EQ(rm.current(), 0);
}

// Test for AqlValue(DocumentData&, ResourceMonitor* = nullptr)
TEST(AqlValueSupervisedTest, MutipleDocumentDataCtorAccountsCorrectSize) {
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

  // checks correct counting with internal logic
  EXPECT_EQ(v1.memoryUsage(), e1);
  EXPECT_EQ(v2.memoryUsage(), e2);
  // checks correct counting with external logic
  EXPECT_EQ(rm.current(), e1 + e2);

  v1.destroy();
  EXPECT_EQ(rm.current(), e2);

  v2.destroy();
  EXPECT_EQ(rm.current(), 0);
}

// Test for AqlValue(string_view, ResourceMonitor* nullptr) <- short str
TEST(AqlValueSupervisedTest, ShortStringViewCtorAccountsCorrectSize) {
  auto& global = GlobalResourceMonitor::instance();
  arangodb::ResourceMonitor rm(global);

  std::string s(15, 'x');  // 15 chars, fits short str (<= 126), not inline
  auto payloadSize = 1 + s.size();  // tag&len (= 1) + chars
  auto expected = ptrOverhead() + payloadSize;

  AqlValue v(std::string_view{s}, &rm);

  // checks correct counting with internal logic
  EXPECT_EQ(v.memoryUsage(), expected);
  // checks correct counting with external logic
  EXPECT_EQ(v.memoryUsage(), rm.current());

  // Slice should decode back to original string
  auto slice = v.slice();
  ASSERT_TRUE(slice.isString());
  EXPECT_EQ(slice.stringView(), s);

  v.destroy();
  // After destruction, usage returns to 0
  EXPECT_EQ(rm.current(), 0);
}

// Test for AqlValue(string_view, ResourceMonitor* nullptr) <- long str
TEST(AqlValueSupervisedTest, LongStringViewCtorAccountsCorrectSize) {
  auto& global = GlobalResourceMonitor::instance();
  arangodb::ResourceMonitor rm(global);

  std::string s(300, 'A');              // triggers long string encoding
  auto payloadSize = 1 + 8 + s.size();  // len + tag + chars
  std::size_t expected = ptrOverhead() + payloadSize;

  AqlValue v(std::string_view{s}, &rm);

  // checks correct counting with internal logic
  EXPECT_EQ(v.memoryUsage(), expected);
  // checks correct counting with external logic
  EXPECT_EQ(v.memoryUsage(), rm.current());

  // Slice should decode back to original string
  auto slice = v.slice();
  ASSERT_TRUE(slice.isString());
  EXPECT_EQ(slice.stringView(), s);

  v.destroy();
  // After destruction, usage returns to 0
  EXPECT_EQ(rm.current(), 0);
}

// Test for AqlValue(Buffer&&, ResourceMonitor* = nullptr)
TEST(AqlValueSupervisedTest, BufferCtorAccountsCorrectSize) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  auto builder = makeLargeArray(2048, 'a');
  Slice slice = builder.slice();
  velocypack::Buffer<uint8_t> buffer;
  buffer.append(slice.start(), slice.byteSize());

  AqlValue aqlVal(buffer, &resourceMonitor);

  auto expected = static_cast<size_t>(slice.byteSize()) + ptrOverhead();
  // checks correct counting with internal logic
  EXPECT_EQ(aqlVal.memoryUsage(), expected);
  // checks correct counting with external logic
  EXPECT_EQ(aqlVal.memoryUsage(), resourceMonitor.current());

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

// Test for AqlValue(Slice, ResourceMonitor* = nullptr)
TEST(AqlValueSupervisedTest, SliceCtorAccountsCorrectSize) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  auto builder = makeLargeArray(1024, 'a');
  Slice slice = builder.slice();
  AqlValue aqlVal(slice, static_cast<ValueLength>(slice.byteSize()),
                  &resourceMonitor);

  auto expected = static_cast<size_t>(slice.byteSize() + ptrOverhead());
  // checks correct counting with internal logic
  EXPECT_EQ(aqlVal.memoryUsage(), expected);
  // checks correct counting with external logic
  EXPECT_EQ(aqlVal.memoryUsage(), resourceMonitor.current());

  EXPECT_TRUE(aqlVal.slice().isArray());
  {
    ValueLength l = 0;
    (void)aqlVal.slice().at(0).getStringUnchecked(l);
    EXPECT_EQ(l, 1024);
  }

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

// Test for AqlValue(Slice, ResourceMonitor* = nullptr)
// This creates multiple supervised AqlValues
TEST(AqlValueSupervisedTest, MultipleSliceCtorAccountsCorrectSize) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  auto bA = makeLargeArray(1000, 'a');
  auto bB = makeLargeArray(2000, 'b');
  auto bC = makeLargeArray(3000, 'c');
  Slice sliceA = bA.slice();
  Slice sliceB = bB.slice();
  Slice sliceC = bC.slice();

  AqlValue a1(sliceA, 0, &resourceMonitor); // SUPERVISED_SLICE
  AqlValue a2(sliceB, 0, &resourceMonitor); // SUPERVISED_SLICE
  AqlValue a3(sliceC, 0, &resourceMonitor); // SUPERVISED_SLICE

  size_t e1 = static_cast<size_t>(sliceA.byteSize()) + ptrOverhead();
  size_t e2 = static_cast<size_t>(sliceB.byteSize()) + ptrOverhead();
  size_t e3 = static_cast<size_t>(sliceC.byteSize()) + ptrOverhead();

  // checks correct counting with internal logic
  EXPECT_EQ(a1.memoryUsage() + a2.memoryUsage() + a3.memoryUsage(),
    e1 + e2 + e3);
  // checks correct counting with external logic
  EXPECT_EQ(a1.memoryUsage() + a2.memoryUsage() + a3.memoryUsage(),
    resourceMonitor.current());

  a1.destroy();
  EXPECT_EQ(resourceMonitor.current(), e2 + e3);

  a2.destroy();
  EXPECT_EQ(resourceMonitor.current(), e3);

  a3.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

// Test for AqlValue(AqlValueHintSliceCopy, ResourceMonitor* = nullptr)
TEST(AqlValueSupervisedTest, HintSliceCopyCtorAccountsCorrectSize) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  auto builder = makeLargeArray(512, 'a');
  Slice slice = builder.slice();
  AqlValueHintSliceCopy hint{slice};
  AqlValue aqlVal(hint, &resourceMonitor);

  auto expected = static_cast<size_t>(slice.byteSize()) + ptrOverhead();
  // checks correct counting with internal logic
  EXPECT_EQ(aqlVal.memoryUsage(), expected);
  // checks correct counting with external logic
  EXPECT_EQ(aqlVal.memoryUsage(), resourceMonitor.current());

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

// Checks the behavior of copy constructor AqlValue(AqlValue const other&)
// For supervised AqlValue (VPACK_SUPERVISED_SLICE, VPACK_SUPERVISED_STRING),
// it will create a new heap obj.
// Other than them, it won't create a new heap obj i.e. shallow copy
TEST(AqlValueSupervisedTest, CopyCtorAccountsCorrectSize) {
  // 1) VPACK_INLINE_INT64
  {
    Builder b;
    b.add(Value(42));
    AqlValue v(b.slice());  // Creates VPACK_INLINE_INT64
    EXPECT_EQ(v.type(), AqlValue::VPACK_INLINE_INT64);

    // Invokes copy constructor; creates another copy of the AqlValue
    AqlValue cpy = v;
    EXPECT_EQ(cpy.type(), v.type());
    ASSERT_EQ(cpy.memoryUsage(), v.memoryUsage());
    EXPECT_TRUE(cpy.slice().binaryEquals(v.slice()));

    cpy.destroy();
    // Checks v is still alive after cpy is destroyed
    EXPECT_TRUE(v.slice().isInteger());
    EXPECT_EQ(v.slice().getNumber<int64_t>(), 42);
    v.destroy();
  }

  // 2) VPACK_INLINE_UINT64
  {
    Builder b;
    uint64_t u = (1ULL << 63);  // 9223372036854775808
    b.add(Value(u));
    AqlValue v(b.slice());  // Creates VPACK_INLINE_UINT64
    EXPECT_EQ(v.type(), AqlValue::VPACK_INLINE_UINT64)
        << "type() = " << static_cast<int>(v.type());

    // Copy constructor
    AqlValue cpy = v;
    EXPECT_EQ(cpy.type(), v.type());
    ASSERT_EQ(cpy.memoryUsage(), v.memoryUsage());
    EXPECT_TRUE(cpy.slice().binaryEquals(v.slice()));

    cpy.destroy();
    // Ensure v is still alive after destroying copy
    EXPECT_TRUE(v.slice().isInteger());
    EXPECT_EQ(v.slice().getNumber<uint64_t>(), 1ULL << 63);
    v.destroy();
  }

  // 3) VPACK_INLINE_DOUBLE
  {
    Builder b;
    b.add(Value(3.1415926535));
    AqlValue v(b.slice());  // Creates VPACK_INLINE_DOUBLE
    EXPECT_EQ(v.type(), AqlValue::VPACK_INLINE_DOUBLE);

    // Copy constructor
    AqlValue cpy = v;
    EXPECT_EQ(cpy.type(), v.type());
    ASSERT_EQ(cpy.memoryUsage(), v.memoryUsage());
    EXPECT_TRUE(cpy.slice().binaryEquals(v.slice()));

    cpy.destroy();
    // Ensure v is still alive after destroying copy
    EXPECT_TRUE(v.slice().isDouble());
    EXPECT_DOUBLE_EQ(v.slice().getNumber<double>(), 3.1415926535);

    v.destroy();
  }

  // // 4) VPACK_MANAGED_SLICE
  // {
  //   std::string big(300, 'a');
  //   arangodb::velocypack::Builder b;
  //   b.add(arangodb::velocypack::Value(big));
  //
  //   AqlValue v(b.slice());  // VPACK_MANAGED_SLICE
  //   ASSERT_EQ(v.type(), AqlValue::VPACK_MANAGED_SLICE);
  //
  //   auto* p1 = v.slice().start();
  //
  //   // Copy constructor; shallow copy
  //   AqlValue cpy = v;
  //   ASSERT_EQ(cpy.type(), AqlValue::VPACK_MANAGED_SLICE);
  //
  //   // Shallow copy -> pointers are identical, contents are identical
  //   EXPECT_EQ(cpy.slice().start(), v.slice().start());
  //   EXPECT_TRUE(cpy.slice().binaryEquals(v.slice()));
  //
  //   // Destroying the copy will destroy the original's heap data too
  //   // So v's pointer is dangling
  //   cpy.destroy();
  // }

  // // 5) MANAGED_STRING — shallow copy
  // {
  //   std::string big(300, 'x');
  //   AqlValue v(std::string_view{big});  // VPACK_MANAGED_STRING
  //   ASSERT_EQ(v.type(), AqlValue::VPACK_MANAGED_STRING);
  //
  //   // Copy ctor; shallow copy
  //   AqlValue cpy = v;
  //   ASSERT_EQ(cpy.type(), AqlValue::VPACK_MANAGED_STRING);
  //
  //   // Same pointers and same contents
  //   EXPECT_EQ(v.data(), cpy.data());
  //   EXPECT_TRUE(cpy.slice().binaryEquals(v.slice()));
  //
  //   // Destroy the copy; the original's heap data is also destroyed
  //   cpy.destroy();
  // }

  // 6) SupervisedSlice: copy ctor deep copy
  {
    auto& g = GlobalResourceMonitor::instance();
    ResourceMonitor rm(g);

    Builder obj = makeObj({{"k", Value(std::string(300, 'a'))}});
    VPackSlice src = obj.slice();

    std::uint64_t base = rm.current();

    AqlValue v(src, /*length*/ 0, &rm);  // Original supervised slice
    ASSERT_EQ(v.type(), AqlValue::VPACK_SUPERVISED_SLICE);
    auto* pv = v.slice().start();
    std::uint64_t afterV = rm.current();
    EXPECT_EQ(afterV, v.memoryUsage());

    // Copy-ctor -> deep copy
    AqlValue cpy = v;
    ASSERT_EQ(cpy.type(), AqlValue::VPACK_SUPERVISED_SLICE);
    auto* pc = cpy.slice().start();

    EXPECT_TRUE(cpy.slice().binaryEquals(v.slice()));  // Same contents
    EXPECT_NE(pc, pv) << "Deep copy must have pointers";
    EXPECT_EQ(rm.current(), afterV * 2) << "Two independent buffers";

    // Destroy the copy; original is still alive
    cpy.destroy();
    EXPECT_EQ(rm.current(), afterV);
    EXPECT_TRUE(v.slice().binaryEquals(src));  // The original is alive
    EXPECT_EQ(v.slice().start(), pv);

    // Destroy the original; RM returns to base
    v.destroy();
    EXPECT_EQ(rm.current(), base);
  }

  // 7) SupervisedString: copy-ctor deep copy
  {
    auto& g = GlobalResourceMonitor::instance();
    ResourceMonitor rm(g);

    std::string big(300, 'x');
    std::uint64_t base = rm.current();

    // Original supervised string
    AqlValue v(std::string_view{big}, &rm);
    ASSERT_EQ(v.type(), AqlValue::VPACK_SUPERVISED_SLICE) << v.type();
    auto* pv = v.slice().start();
    std::uint64_t afterV = rm.current();
    EXPECT_EQ(afterV, v.memoryUsage());

    // Copy-ctor; deep copy
    AqlValue cpy = v;
    ASSERT_EQ(cpy.type(), AqlValue::VPACK_SUPERVISED_SLICE);
    auto* pc = cpy.slice().start();

    EXPECT_TRUE(cpy.slice().binaryEquals(v.slice()));  // Same contents
    EXPECT_NE(pc, pv) << "Deep copy must have pointers";
    EXPECT_EQ(rm.current(), afterV * 2) << "Two independent buffers";

    // Destroy the copy; original is still alive
    cpy.destroy();
    EXPECT_EQ(rm.current(), afterV);
    EXPECT_TRUE(v.slice().isString());  // The original is alive
    EXPECT_EQ(v.slice().getStringLength(), big.size());
    EXPECT_EQ(v.slice().start(), pv);

    // Destroy the original; RM returns to base
    v.destroy();
    EXPECT_EQ(rm.current(), base);
  }
}

// Test if small value won't create a Supervised AqlValue
TEST(AqlValueSupervisedTest, InlineCtorNotAccount) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  auto builder = makeString(14, 'a');
  Slice slice = builder.slice();
  // Passing resourceMonitor*, but won't create a supervised AqlValue
  AqlValue aqlVal(slice, 0, &resourceMonitor);

  EXPECT_EQ(aqlVal.memoryUsage(), 0); // No external memory usage
  EXPECT_EQ(resourceMonitor.current(), 0); // No increase for resourceMonitor
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

// Test the boundary when AqlValue allocates data in external memory space
TEST(AqlValueSupervisedTest, BoundaryOverInlineCtorAccounts) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  // This is the very boundary when AqlValue allocates the data in the heap
  auto builder = makeString(16, 'a');
  Slice slice = builder.slice();
  AqlValue aqlVal(slice, 0, &resourceMonitor);

  auto expected = static_cast<size_t>(slice.byteSize()) + ptrOverhead();
  // checks correct counting with internal logic
  EXPECT_EQ(aqlVal.memoryUsage(), expected);
  // checks correct counting with external logic
  EXPECT_EQ(aqlVal.memoryUsage(), resourceMonitor.current());

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

// Test the behavior of AqlValue(uint8_t const* pointer) -> VPACK_SLICE_POINTER
TEST(AqlValueSupervisedTest, PointerCtorNotAccount) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  auto builder1 = makeLargeArray(3072, 'a');
  auto builder2 = makeLargeArray(3072, 'b');
  Slice slice1 = builder1.slice();
  Slice slice2 = builder2.slice();

  auto expected = static_cast<size_t>(slice1.byteSize()) + ptrOverhead();
  AqlValue owned(slice1, 0, &resourceMonitor);
  ASSERT_EQ(owned.memoryUsage(), expected);
  ASSERT_EQ(owned.memoryUsage(), resourceMonitor.current());

  // This just shares the pointer, won't create new obj.
  // Creates VPACK_SLICE_POINTER
  AqlValue adopted(slice2.begin());

  // Creating VPACK_SLICE_POINTER won't increase resourceMonitor memory usage
  EXPECT_EQ(resourceMonitor.current(), expected);
  EXPECT_EQ(adopted.memoryUsage(), 0);

  adopted.destroy();
  // resourceMonitor memory usage won't be affected
  EXPECT_EQ(resourceMonitor.current(), expected);

  owned.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

// Test the behavior of AqlValue(uint8_t const* pointer) -> VPACK_SLICE_POINTER
// Even if it takes pointer of SupervisedBuffer, it shouldn't count memory
TEST(AqlValueSupervisedTest, PointerCtorForSupervisedBufferNotAccount) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  // Creates supervisedBuffer obj
  SupervisedBuffer supervised(resourceMonitor);
  Builder builder(supervised);
  builder.openArray();
  builder.add(Value(std::string(1500, 'a')));
  builder.close();

  auto before = resourceMonitor.current();

  AqlValue adopted(builder.slice().begin()); // VPAKC_SLICE_POINTER
  EXPECT_EQ(adopted.memoryUsage(), 0);
  // Memory usage of resourceMonitor should not increase
  EXPECT_EQ(resourceMonitor.current(), before);

  adopted.destroy();
  // Memory usage of resourceMonitor should not decrease
  EXPECT_EQ(resourceMonitor.current(), before);
}

// Test the behavior of clone(); for supervised AqlValue, it should create
// a new copy of heap obj, hence counts double memory usage
TEST(AqlValueSupervisedTest, FuncCloneCreatesAnotherCopy) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  Builder builder;
  builder.openArray();
  builder.add(Value(std::string(1024, 'a')));
  builder.close();
  Slice slice = builder.slice();

  AqlValue aqlVal(slice, 0, &resourceMonitor); // SUPERVISED_SLICE
  AqlValue cloneVal = aqlVal.clone(); // Create new copy of heap data
  // Those AqlValues are independent, so memory usage should be doubled
  EXPECT_EQ(resourceMonitor.current(),
            aqlVal.memoryUsage() + cloneVal.memoryUsage());

  aqlVal.destroy();
  // cloneVal is still alive
  EXPECT_EQ(resourceMonitor.current(), cloneVal.memoryUsage());

  cloneVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

// ???
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

// Test the behavior of duplicate destroy()
TEST(AqlValueSupervisedTest, DuplicateDestoryIsSafe) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  auto b = makeLargeArray(2000, 'a');
  Slice slice = b.slice();
  AqlValue aqlVal(slice, 0, &resourceMonitor);
  auto expected = slice.byteSize() + ptrOverhead();
  EXPECT_EQ(aqlVal.memoryUsage(), expected);
  EXPECT_EQ(aqlVal.memoryUsage(), resourceMonitor.current());

  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);

  // destroy() calls erase() where zero outs the AqlValue's 16 bytes
  aqlVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
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
  EXPECT_FALSE(copied1);  // This should be true

  EXPECT_TRUE(v1.slice().binaryEquals(obj.slice()));
  EXPECT_TRUE(mat1.slice().binaryEquals(obj.slice()));

  // Because there are two copies of SupervisedSlice AqlValues
  EXPECT_EQ(rm.current(), 2 * base);

  mat1.destroy();
  EXPECT_EQ(rm.current(), base);

  v1.destroy();
  EXPECT_EQ(rm.current(), 0);

  /* Non-range SupervisedString */
  std::string bigStr(16 * 1024, 'y');          // 16KB string
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