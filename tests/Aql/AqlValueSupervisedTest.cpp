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

  AqlValue a1(sliceA, 0, &resourceMonitor);  // SUPERVISED_SLICE
  AqlValue a2(sliceB, 0, &resourceMonitor);  // SUPERVISED_SLICE
  AqlValue a3(sliceC, 0, &resourceMonitor);  // SUPERVISED_SLICE

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

  // 4) VPACK_MANAGED_SLICE
  {
    std::string big(300, 'a');
    arangodb::velocypack::Builder b;
    b.add(arangodb::velocypack::Value(big));

    AqlValue v(b.slice());  // VPACK_MANAGED_SLICE
    ASSERT_EQ(v.type(), AqlValue::VPACK_MANAGED_SLICE);

    // Copy constructor; shallow copy
    AqlValue cpy = v;
    ASSERT_EQ(cpy.type(), AqlValue::VPACK_MANAGED_SLICE);

    // Shallow copy -> pointers are identical, contents are identical
    EXPECT_EQ(cpy.slice().start(), v.slice().start());
    EXPECT_TRUE(cpy.slice().binaryEquals(v.slice()));

    // Destroying the copy will destroy the original's heap data too
    // BE AWARE: v's pointer is dangling
    cpy.destroy();
  }

  // 5) MANAGED_STRING — shallow copy
  {
    Builder b = makeString(300, 'x');
    Slice s = b.slice();
    auto doc = makeDocDataFromSlice(s);
    AqlValue v(doc);  // VPACK_MANAGED_STRING
    ASSERT_EQ(v.type(), AqlValue::VPACK_MANAGED_STRING);

    // Copy ctor; shallow copy
    AqlValue cpy = v;
    ASSERT_EQ(cpy.type(), AqlValue::VPACK_MANAGED_STRING);

    // Same pointers and same contents
    EXPECT_EQ(v.data(), cpy.data());
    EXPECT_TRUE(cpy.slice().binaryEquals(v.slice()));

    // Destroy the copy; the original's heap data is also destroyed
    // BE AWARE: v's pointer is dangling
    cpy.destroy();
  }

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
    std::uint64_t base = rm.current();

    Builder b = makeString(300, 'x');
    Slice s = b.slice();
    auto doc = makeDocDataFromSlice(s);
    AqlValue v(doc, &rm); // Original supervised string
    ASSERT_EQ(v.type(), AqlValue::VPACK_SUPERVISED_STRING) << v.type();
    auto* pv = v.slice().start();
    std::uint64_t afterV = rm.current();
    EXPECT_EQ(afterV, v.memoryUsage());

    // Copy-ctor; deep copy
    AqlValue cpy = v;
    ASSERT_EQ(cpy.type(), AqlValue::VPACK_SUPERVISED_STRING);
    auto* pc = cpy.slice().start();

    EXPECT_TRUE(cpy.slice().binaryEquals(v.slice()));  // Same contents
    EXPECT_NE(pc, pv) << "Deep copy must have pointers";
    EXPECT_EQ(rm.current(), afterV * 2) << "Two independent buffers";

    // Destroy the copy; original is still alive
    cpy.destroy();
    EXPECT_EQ(rm.current(), afterV);
    EXPECT_TRUE(v.slice().isString());  // The original is alive
    EXPECT_EQ(v.slice().getStringLength(), 300);
    EXPECT_EQ(v.slice().start(), pv);

    // Destroy the original; RM returns to base
    v.destroy();
    EXPECT_EQ(rm.current(), base);
  }
}

// Test if small value won't create a Supervised AqlValue
TEST(AqlValueSupervisedTest, InlineCtorNotAccounts) {
  auto& global = GlobalResourceMonitor::instance();
  ResourceMonitor resourceMonitor(global);

  auto builder = makeString(14, 'a');
  Slice slice = builder.slice();
  // Passing resourceMonitor*, but won't create a supervised AqlValue
  AqlValue aqlVal(slice, 0, &resourceMonitor);

  EXPECT_EQ(aqlVal.memoryUsage(), 0);       // No external memory usage
  EXPECT_EQ(resourceMonitor.current(), 0);  // No increase for resourceMonitor
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

  AqlValue adopted(builder.slice().begin());  // VPAKC_SLICE_POINTER
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

  AqlValue aqlVal(slice, 0, &resourceMonitor);  // SUPERVISED_SLICE
  AqlValue cloneVal = aqlVal.clone();           // Create new copy of heap data
  // Those AqlValues are independent, so memory usage should be doubled
  EXPECT_EQ(resourceMonitor.current(),
            aqlVal.memoryUsage() + cloneVal.memoryUsage());

  aqlVal.destroy();
  // cloneVal is still alive
  EXPECT_EQ(resourceMonitor.current(), cloneVal.memoryUsage());

  cloneVal.destroy();
  EXPECT_EQ(resourceMonitor.current(), 0);
}

// Test the behavior of duplicate destroy()
TEST(AqlValueSupervisedTest, DuplicateDestroysAreSafe) {
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

// ???
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

// Test the behavior of at() function
// If bool doCopy = true, creates a copy of AqlValue
TEST(AqlValueSupervisedTest, FuncAtWithDoCopyTrueReturnsCopy) {
  auto& g = GlobalResourceMonitor::instance();
  ResourceMonitor rm(g);

  Builder arr = makeArray({
      Value(std::string(2048, 'a')),
      Value(std::string(2048, 'b')),
      Value(std::string(2048, 'c')),
  });

  AqlValue a(arr.slice(), 0, &rm);
  auto originalSize = arr.slice().byteSize() + ptrOverhead();
  ASSERT_EQ(a.memoryUsage(), originalSize);
  ASSERT_EQ(a.memoryUsage(), rm.current());

  bool mustDestroy = false;
  // doCopy = false -> NOT create copy, mustDestroy remains false
  // This creates VPACK_SLICE_POINTER AqlValue -> zero memory usage
  AqlValue e0 = a.at(1, mustDestroy, /*doCopy*/ false);
  EXPECT_FALSE(mustDestroy);
  EXPECT_EQ(e0.slice().getStringLength(), 2048);
  EXPECT_EQ(e0.memoryUsage(), 0);  // This should be zero
  // memory for resourceMonitor should not change
  EXPECT_EQ(rm.current(), originalSize);

  // doCopy = true -> Creates copy, mustDestroy changes to true
  // This creates a new copy of SupervisedSlice AqlValue
  AqlValue e1 = a.at(2, mustDestroy, /*doCopy*/ true);
  EXPECT_TRUE(mustDestroy);
  EXPECT_EQ(e1.slice().getStringLength(), 2048);
  EXPECT_GE(e1.memoryUsage(), ptrOverhead() + 2048);
  EXPECT_EQ(rm.current(), originalSize + e1.memoryUsage());

  e1.destroy();  // This destroy should affect memory usage of ResourceMonitor
  EXPECT_EQ(rm.current(), originalSize);

  a.destroy();
  EXPECT_EQ(rm.current(), 0);
}

// Test behavior of data() function
// data() should return pointer to actual heap data (not resourceMonitor*)
TEST(AqlValueSupervisedTest, FuncDataReturnsPointerToActualData) {
  auto& g = GlobalResourceMonitor::instance();
  ResourceMonitor rm(g);

  // 1) SupervisedSlice
  Builder b1 = makeString(300, 'a');
  Slice s1 = b1.slice();

  AqlValue a1(s1, 0, &rm);  // supervised slice
  auto e1 = s1.byteSize() + ptrOverhead();
  EXPECT_EQ(a1.type(), AqlValue::VPACK_SUPERVISED_SLICE);
  EXPECT_EQ(a1.memoryUsage(), e1);
  EXPECT_EQ(a1.memoryUsage(), rm.current());

  // data() must point to the beginning of this value's slice payload
  // Not points to resourceMonitor*
  EXPECT_EQ(static_cast<uint8_t const*>(a1.data()), a1.slice().start());

  // 2) SupervisedString
  Builder b2 = makeString(512, 'b');  // also large
  Slice s2 = b2.slice();
  auto doc = makeDocDataFromSlice(s2);
  AqlValue a2(doc, &rm);  // supervised string
  auto e2 = s2.byteSize() + ptrOverhead();
  EXPECT_EQ(a2.type(), AqlValue::VPACK_SUPERVISED_STRING);
  EXPECT_EQ(a2.memoryUsage(), e2);
  EXPECT_EQ(a1.memoryUsage() + a2.memoryUsage(), rm.current());

  // data() must point to this value's own string payload.
  EXPECT_EQ(static_cast<uint8_t const*>(a2.data()), a2.slice().start());

  a2.destroy();
  EXPECT_EQ(rm.current(), a1.memoryUsage());
  a1.destroy();
  EXPECT_EQ(rm.current(), 0u);
}

// Test the behavior of materialize() function's default case
TEST(AqlValueSupervisedTest, FuncMaterializeForSupervisedAqlValueReturnsCopy) {
  auto& g = GlobalResourceMonitor::instance();
  ResourceMonitor rm(g);

  /* Non-range SupervisedSlice */
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
  // Copy ctor of SupervisedSlice creates a new copy of AqlValue => clone
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
  std::string bigStr(16 * 1024, 'y');
  AqlValue v2(std::string_view{bigStr}, &rm);  // SupervisedString
  base = rm.current();

  bool copied2 = false;
  AqlValue mat2 = v2.materialize(nullptr, copied2);  // This is clone
  EXPECT_FALSE(copied2);
  EXPECT_TRUE(mat2.slice().isString());
  EXPECT_EQ(mat2.slice().stringView(), bigStr);

  EXPECT_EQ(rm.current(), 2 * base);  // cloned supervised string accounted

  mat2.destroy();
  EXPECT_EQ(rm.current(), base);

  v2.destroy();
  EXPECT_EQ(rm.current(), 0);
}

// Test if slice() returns slice of actual data
TEST(AqlValueSupervisedTest,
     FuncSliceWithAqlValueTypeReturnsSliceOfActualData) {
  auto& g = GlobalResourceMonitor::instance();
  ResourceMonitor rm(g);

  /* SUPERVISED_SLICE */
  Builder b1 = makeString(300, 'a');
  Slice s1 = b1.slice();
  AqlValue a1(s1, 0, &rm);  // supervised slice
  EXPECT_EQ(a1.type(), AqlValue::VPACK_SUPERVISED_SLICE);
  {
    auto sl = a1.slice();
    EXPECT_EQ(sl.getStringLength(), 300);
    // Must point at the actual payload
    EXPECT_EQ(sl.start(), static_cast<uint8_t const*>(a1.data()));
  }

  /* SUPERVISED_STRING */
  Builder b2 = makeString(512, 'b');
  Slice s2 = b2.slice();
  auto doc = makeDocDataFromSlice(s2);
  AqlValue a2(doc, &rm);  // supervised string
  EXPECT_EQ(a2.type(), AqlValue::VPACK_SUPERVISED_STRING);
  {
    auto sl = a2.slice(AqlValue::VPACK_SUPERVISED_STRING);
    EXPECT_EQ(sl.getStringLength(), 512);
    // Must point at the actual payload
    EXPECT_EQ(sl.start(), static_cast<uint8_t const*>(a2.data()));
  }

  a2.destroy();
  a1.destroy();
  EXPECT_EQ(rm.current(), 0u);
}

// Test the behavior of operator==; ManagedSlice should be equal to SupervisedSlice
// as long as the heap data are the same
TEST(AqlValueSupervisedTest, ManagedSliceIsEqualToSupervisedSlice) {
  auto& g = GlobalResourceMonitor::instance();
  ResourceMonitor rm(g);

  Builder a = makeString(300, 'a');
  Builder b = makeString(300, 'b');
  Slice sa = a.slice();
  Slice sb = b.slice();

  AqlValue managedA1(sa);
  ASSERT_EQ(managedA1.type(), AqlValue::VPACK_MANAGED_SLICE);
  AqlValue managedA2(sa);
  ASSERT_EQ(managedA2.type(), AqlValue::VPACK_MANAGED_SLICE);
  AqlValue supervisedA1(sa, 0, &rm);
  ASSERT_EQ(supervisedA1.type(), AqlValue::VPACK_SUPERVISED_SLICE);
  AqlValue supervisedA2(sa, 0, &rm);
  ASSERT_EQ(supervisedA2.type(), AqlValue::VPACK_SUPERVISED_SLICE);
  AqlValue supervisedB1(sb, 0, &rm);
  ASSERT_EQ(supervisedB1.type(), AqlValue::VPACK_SUPERVISED_SLICE);
  AqlValue supervisedB2(sb, 0, &rm);
  ASSERT_EQ(supervisedB2.type(), AqlValue::VPACK_SUPERVISED_SLICE);

  std::equal_to<AqlValue> eq;
  // They should be equal
  EXPECT_TRUE(eq(managedA1, supervisedA1));
  EXPECT_TRUE(eq(managedA1, supervisedA2));
  EXPECT_TRUE(eq(managedA2, supervisedA1));
  EXPECT_TRUE(eq(managedA2, supervisedA2));

  EXPECT_TRUE(eq(supervisedA1, supervisedA2));

  EXPECT_FALSE(eq(managedA1, supervisedB1));
  EXPECT_FALSE(eq(managedA1, supervisedB2));
  EXPECT_FALSE(eq(managedA2, supervisedB1));
  EXPECT_FALSE(eq(managedA2, supervisedB2));

  EXPECT_FALSE(eq(supervisedA1, supervisedB1));

  managedA1.destroy();
  managedA2.destroy();
  supervisedA1.destroy();
  supervisedA2.destroy();
  supervisedB1.destroy();
  supervisedB2.destroy();
}

TEST(AqlValueSupervisedTest, CompareBetweenManagedAndSupervisedReturnSame) {
  auto& g = GlobalResourceMonitor::instance();
  ResourceMonitor rm(g);

  Builder a = makeString(300, 'a');
  Builder b = makeString(300, 'b');
  Slice sa = a.slice();
  Slice sb = b.slice();

  AqlValue managedA1(sa);
  ASSERT_EQ(managedA1.type(), AqlValue::VPACK_MANAGED_SLICE);
  AqlValue managedA2(sa);
  ASSERT_EQ(managedA2.type(), AqlValue::VPACK_MANAGED_SLICE);
  AqlValue supervisedA1(sa, 0, &rm);
  ASSERT_EQ(supervisedA1.type(), AqlValue::VPACK_SUPERVISED_SLICE);
  AqlValue supervisedA2(sa, 0, &rm);
  ASSERT_EQ(supervisedA2.type(), AqlValue::VPACK_SUPERVISED_SLICE);
  AqlValue supervisedB1(sb, 0, &rm);
  ASSERT_EQ(supervisedB1.type(), AqlValue::VPACK_SUPERVISED_SLICE);
  AqlValue supervisedB2(sb, 0, &rm);
  ASSERT_EQ(supervisedB2.type(), AqlValue::VPACK_SUPERVISED_SLICE);

  // These are the same
  EXPECT_EQ(AqlValue::Compare(nullptr, managedA1, supervisedA1, /*utf8*/ true), 0);
  EXPECT_EQ(AqlValue::Compare(nullptr, managedA1, supervisedA2, /*utf8*/ true), 0);
  EXPECT_EQ(AqlValue::Compare(nullptr, managedA2, supervisedA1, /*utf8*/ true), 0);
  EXPECT_EQ(AqlValue::Compare(nullptr, managedA2, supervisedA2, /*utf8*/ true), 0);
  EXPECT_EQ(AqlValue::Compare(nullptr, supervisedA1, supervisedA2, /*utf8*/ true), 0);

  // These are different
  EXPECT_EQ(AqlValue::Compare(nullptr, managedA1, supervisedB1, /*utf8*/ true), -1);
  EXPECT_EQ(AqlValue::Compare(nullptr, managedA1, supervisedB2, /*utf8*/ true), -1);
  EXPECT_EQ(AqlValue::Compare(nullptr, managedA2, supervisedB1, /*utf8*/ true), -1);
  EXPECT_EQ(AqlValue::Compare(nullptr, managedA2, supervisedB2, /*utf8*/ true), -1);
  EXPECT_EQ(AqlValue::Compare(nullptr, supervisedA1, supervisedB2, /*utf8*/ true), -1);

  EXPECT_EQ(AqlValue::Compare(nullptr, supervisedB1, managedA1, /*utf8*/ true), 1);
  EXPECT_EQ(AqlValue::Compare(nullptr, supervisedB1, managedA2, /*utf8*/ true), 1);
  EXPECT_EQ(AqlValue::Compare(nullptr, supervisedB2, managedA1, /*utf8*/ true), 1);
  EXPECT_EQ(AqlValue::Compare(nullptr, supervisedB2, managedA2, /*utf8*/ true), 1);
  EXPECT_EQ(AqlValue::Compare(nullptr, supervisedB1, supervisedA1, /*utf8*/ true), 1);

  managedA1.destroy();
  managedA2.destroy();
  supervisedA1.destroy();
  supervisedA2.destroy();
  supervisedB1.destroy();
  supervisedB2.destroy();
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

TEST(AqlValueSupervisedTest, RequiresDestructionFuncForSupervisedAqlValueReturnsTrue) {
  auto& g = GlobalResourceMonitor::instance();
  ResourceMonitor rm(g);

  Builder b;
  b.add(Value(std::string(200, 'a')));
  AqlValue supSlice(b.slice(), 0, &rm);
  EXPECT_EQ(supSlice.type(), AqlValue::VPACK_SUPERVISED_SLICE);
  EXPECT_TRUE(supSlice.requiresDestruction()); // This should return true

  supSlice.destroy();
  EXPECT_EQ(rm.current(), 0U);
}

TEST(AqlValueSupervisedTest, Compare_SupervisedStrings_Utf8Toggle) {
  auto& g = GlobalResourceMonitor::instance();
  ResourceMonitor rm(g);

  // Make supervised strings via slice ctor with RM (short strings become
  // supervised slice in your impl) "apple" < "banana" under both binary and
  // UTF-8 compares
  {
    arangodb::velocypack::Builder s1;
    s1.add(arangodb::velocypack::Value("apple"));
    arangodb::velocypack::Builder s2;
    s2.add(arangodb::velocypack::Value("banana"));
    AqlValue v1(s1.slice(), 0, &rm);
    AqlValue v2(s2.slice(), 0, &rm);

    EXPECT_LT(AqlValue::Compare(nullptr, v1, v2, /*utf8*/ false), 0);
    EXPECT_LT(AqlValue::Compare(nullptr, v1, v2, /*utf8*/ true), 0);

    v1.destroy();
    v2.destroy();
  }

  // Also check equality path (same supervised content)
  {
    arangodb::velocypack::Builder s1;
    s1.add(arangodb::velocypack::Value("same"));
    arangodb::velocypack::Builder s2;
    s2.add(arangodb::velocypack::Value("same"));
    AqlValue v1(s1.slice(), 0, &rm);
    AqlValue v2(s2.slice(), 0, &rm);

    EXPECT_EQ(AqlValue::Compare(nullptr, v1, v2, /*utf8*/ false), 0);
    EXPECT_EQ(AqlValue::Compare(nullptr, v1, v2, /*utf8*/ true), 0);

    v1.destroy();
    v2.destroy();
  }

  EXPECT_EQ(rm.current(), 0U);
}
